"""
supervisor가 어디에도 매칭시키지 못한 질문(open_qa)을 위한 폴백 경로.
13개 일반 시나리오 항목이나 특수상황처럼 미리 정해진 topic_tag가 없으므로,
전체 임베딩 테이블에서 검색한다 — 단, source_type 쿼터 + distance 임계값으로
균형을 맞춘다(단위 28: search_balanced). 한 종류(주로 판례)가 컨텍스트를 독점해
조문이 없는데도 원문→해설→상황적용을 지어내던 문제를 막고, 근거(법령원문)를 못 찾으면
억지 생성 대신 '근거 없음' 문구로 빠진다. ReAct식 반복검색은 턴당 비용/지연 대비 실익이
적다고 판단해 여전히 도입하지 않는다(단일 검색).
"""
from app.graph.parts.d_part.nodes._context import format_chunks
from app.graph.parts.d_part.schemas import DPartGraphState, get_active_query
from app.llm import d_part as llm_d_part
from app.rag.retrievers.d_part import DPartRetriever

_retriever = DPartRetriever()

# 단위 28: 쿼터/임계값으로도 뒷받침 근거(특히 법령원문)를 못 찾으면 response_open_qa.md의
# 원문→해설→상황적용을 억지로 생성하지 않고 이 문구로 빠진다. finalize의
# _FALLTHROUGH_MESSAGE("아무 데도 안 걸림")와는 구분 — 여기는 "질의는 받았으나 근거 없음".
# victim_check._FALLBACK_MESSAGE 톤을 따르며, 실질 법률정보가 아니라 면책은 붙이지 않는다.
_NO_EVIDENCE_MESSAGE = (
    "질문하신 내용과 관련된 법령이나 판례 자료를 찾지 못했습니다. "
    "정확한 안내를 위해 전문가(변호사·대한법률구조공단 등) 상담을 받아보시길 권해드립니다."
)


async def handle_open_qa(state: DPartGraphState) -> DPartGraphState:
    query = get_active_query(state)
    chunks = await _retriever.search_balanced(query)
    state["retrieved_chunks"] = chunks

    # 근거가 될 법령원문이 없으면 원문→해설→상황적용을 지어내지 않고 '근거 없음'으로 빠진다.
    if not any(c.source_type == "법령원문" for c in chunks):
        # 판례/HUG만 걸렸어도 근거 카드(META)를 내보내면 '근거 없음' 메시지와 모순되므로 비운다(단위 46).
        state["retrieved_chunks"] = []
        state["final_answer"] = _NO_EVIDENCE_MESSAGE
        return state

    context = format_chunks(chunks)
    state["answer_kind"] = "open_qa"
    state["response_stream"] = llm_d_part.generate_response(context, "open_qa")
    return state
