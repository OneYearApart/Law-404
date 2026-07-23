"""
특수상황(인지형) 실행 노드 — 카테고리는 supervisor가 이미 situation.special_case에 담아둔다.
2026 리팩터링(작업단위 49): 하드코딩 안내문 → RAG 실행 노드로 전환.
해설(사례 패턴)은 카테고리별 topic_tag로 판례/HUG를 검색해 generate_response로 grounding한다.

지원절차 개요는 이 노드가 붙이지 않는다 — "인정받은 사용자에게 지원절차를 보여줄지"는 상황
질문이지 "special_cases가 실행됐는지"가 아니다. support_appendix가 상황모델을 보고 정한다(D3).
"""

from app.graph.parts.d_part.nodes._context import build_context
from app.graph.parts.d_part.schemas import SPECIAL_CASE_TOPIC_TAGS, DPartGraphState
from app.llm import d_part as llm_d_part
from app.rag.retrievers.d_part import DPartRetriever

_retriever = DPartRetriever()


async def match_special_case(state: DPartGraphState) -> DPartGraphState:
    """supervisor가 분류한 situation.special_case로 판례/HUG RAG 해설 스트림을 세팅한다.
    이미 final_answer가 세팅된 턴은 건드리지 않고 통과한다."""
    if state.get("final_answer") is not None:
        return state

    category = state["situation"].special_case
    topic_key = SPECIAL_CASE_TOPIC_TAGS[category]

    query_text = f"{category} {state['user_input']}"
    retrieved = await _retriever.search_by_topic(topic_key, query_text)
    state["retrieved_chunks"] = (
        retrieved["statute"]
        + retrieved["case_law"]
        + retrieved["cases"]
        + retrieved["guides"]
    )

    context = build_context(
        state["retrieved_chunks"],
        header=f"특수상황: {category}",
        query=state["user_input"],
    )
    state["answer_kind"] = "special_case"
    state["response_stream"] = llm_d_part.generate_response(context, "special_case")
    return state
