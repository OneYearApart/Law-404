"""
특수상황(인지형) 실행 노드 — supervisor가 special_case_matched를 이미 채운다.
2026 리팩터링(작업단위 49): 하드코딩 안내문 → RAG 실행 노드로 전환.
- 해설(사례 패턴): 카테고리별 topic_tag로 판례/HUG를 검색해 generate_response로 grounding.
- 지원절차 개요(대응 절차 사실): §14.1대로 하드코딩 유지, finalize가 appendix_text로 결정론 append.
미인지형 판정 경로(response_assembly + 작업단위 43~45 액션플랜)와 대칭 구조가 된다.
"""
from app.graph.parts.d_part.nodes._context import format_chunks
from app.graph.parts.d_part.schemas import DPartGraphState, SPECIAL_CASE_TOPIC_TAGS, get_active_query
from app.llm import d_part as llm_d_part
from app.rag.retrievers.d_part import DPartRetriever

_retriever = DPartRetriever()

# 지원절차 개요(대응 절차 사실)만 — 해설은 RAG가 담당하므로 사례 설명 문장은 제거함.
# 문구/지원수단 적용요건은 검수 대상(기획서 §7). 면책은 finalize가 자동 첨부.
_SPECIAL_CASE_GUIDANCE: dict[str, str] = {
    "임대인 사망/파산": (
        "■ 대응\n"
        "- 상속인 또는 파산관재인을 상대로 보증금 반환을 청구하실 수 있습니다.\n"
        "- 경·공매 절차에서 우선매수권·경공매 유예를 활용할 수 있는지 관할 법원·법률구조공단과 확인하시길 권해드립니다."
    ),
    "신탁사기": (
        "■ 대응\n"
        "- 신탁원부를 확인해 임대인이 임대 권한을 위임받았는지 확인하시길 권해드립니다.\n"
        "- 조세채권 안분 등 관련 구제 절차 상담을 권해드립니다."
    ),
    "다가구주택": (
        "■ 대응\n"
        "- 등기부등본과 확정일자 순위로 선순위 임차인 현황을 확인하시길 권해드립니다."
    ),
    "공인중개사 허위고지": (
        "■ 대응\n"
        "- 공인중개사법에 따라 손해배상을 청구하실 수 있습니다.\n"
        "- 중개대상물 확인설명서와 계약 당시 정황을 근거자료로 확보해두시길 권해드립니다."
    ),
}


async def match_special_case(state: DPartGraphState) -> DPartGraphState:
    """supervisor가 분류한 special_case_matched로 (a) 판례/HUG RAG 해설 스트림을 세팅하고
    (b) 지원절차 개요를 appendix_text로 넘긴다. 이미 final_answer가 세팅된 턴(스테이지 확인질문
    대기 등)은 건드리지 않고 통과한다."""
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
    state["appendix_text"] = _SPECIAL_CASE_GUIDANCE[category]   # finalize가 해설 뒤·면책 앞에 append
    return state
