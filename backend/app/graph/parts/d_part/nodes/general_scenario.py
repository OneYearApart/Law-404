"""
일반 시나리오(13개 항목) 실행 노드 — 카테고리 판단은 supervisor가 이미 끝내고
state["general_topic_matched"]에 채워 넘긴다. 이 노드는 그 항목에 대해
RAG 검색(조문+판례+HUG사례집) + 응답 생성만 담당한다.
response_assembly.py(요건판정 결과 기반 RAG+응답 생성)와 결합 구조가 유사하지만
검색 기준(topic_tag vs 요건슬롯)이 달라 노드는 분리돼 있다.
"""
from app.graph.parts.d_part.schemas import DPartGraphState, GENERAL_TOPIC_LABELS
from app.llm import d_part as llm_d_part
from app.rag.retrievers.d_part import DPartRetriever

_retriever = DPartRetriever()


def _format_context(topic_key: str, retrieved: list) -> str:
    lines = [f"항목: {GENERAL_TOPIC_LABELS[topic_key]}"]
    for chunk in retrieved:
        lines.append(f"[{chunk.source_type}] {chunk.content}")
    return "\n".join(lines)


async def handle_general_scenario(state: DPartGraphState) -> DPartGraphState:
    """supervisor가 이미 분류한 general_topic_matched로 RAG 검색+응답 생성만 수행한다.
    이미 final_answer가 세팅된 턴(예: stage_router 확인질문 대기 중)은 건드리지 않고 통과한다."""
    if state.get("final_answer") is not None:
        return state

    topic_key = state["general_topic_matched"]
    retrieved = await _retriever.search_by_topic(topic_key, GENERAL_TOPIC_LABELS[topic_key])
    state["retrieved_chunks"] = (retrieved["statute"] + retrieved["case_law"]
                                 + retrieved["cases"] + retrieved["guides"])

    context = _format_context(topic_key, state["retrieved_chunks"])
    state["response_stream"] = llm_d_part.generate_response(context)
    return state
