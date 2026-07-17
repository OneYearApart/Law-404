"""
특수상황(인지형) 실행 노드 — supervisor가 special_case_matched를 이미 채운다.
2026 리팩터링(작업단위 49): 하드코딩 안내문 → RAG 실행 노드로 전환.
해설(사례 패턴)은 카테고리별 topic_tag로 판례/HUG를 검색해 generate_response로 grounding한다.

지원절차 개요는 이 노드가 붙이지 않는다 — "인정받은 사용자에게 지원절차를 보여줄지"는 상황
질문이지 "special_cases가 실행됐는지"가 아니다. support_appendix가 상황모델을 보고 정한다(D3).
"""
from app.graph.parts.d_part.nodes._context import format_chunks
from app.graph.parts.d_part.schemas import DPartGraphState, SPECIAL_CASE_TOPIC_TAGS, get_active_query
from app.llm import d_part as llm_d_part
from app.rag.retrievers.d_part import DPartRetriever

_retriever = DPartRetriever()


async def match_special_case(state: DPartGraphState) -> DPartGraphState:
    """supervisor가 분류한 special_case_matched로 판례/HUG RAG 해설 스트림을 세팅한다.
    이미 final_answer가 세팅된 턴(스테이지 확인질문 대기 등)은 건드리지 않고 통과한다."""
    if state.get("final_answer") is not None:
        return state

    category = state["special_case_matched"]
    topic_key = SPECIAL_CASE_TOPIC_TAGS[category]

    query_text = f"{category} {get_active_query(state)}"
    retrieved = await _retriever.search_by_topic(topic_key, query_text)
    state["retrieved_chunks"] = (retrieved["statute"] + retrieved["case_law"]
                                 + retrieved["cases"] + retrieved["guides"])

    context = f"특수상황: {category}\n\n{format_chunks(state['retrieved_chunks'])}"
    state["answer_kind"] = "special_case"
    state["response_stream"] = llm_d_part.generate_response(context, "special_case")
    return state
