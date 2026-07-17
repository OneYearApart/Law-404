"""
topic이 없는 두 경로(open_qa / recognized_general)가 공유하는 전체 검색.

둘 다 미리 정해진 topic_tag가 없어 전체 임베딩 테이블을 훑는다(단위 28: search_balanced —
source_type 쿼터 + distance 임계값으로 균형을 맞춰, 한 종류(주로 판례)가 컨텍스트를 독점해
조문이 없는데도 해설·상황적용을 지어내던 문제를 막는다).

뒷받침할 법령원문을 못 찾으면 억지 생성 대신 '근거 없음'으로 빠지는 규칙도 함께 공유한다.
한쪽에만 두면 다른 쪽이 조용히 조문을 지어낸다 — 두 경로가 같은 검색을 쓰는 이상 이 규칙은
경로가 아니라 검색에 딸린 것이다.
"""
from app.graph.parts.d_part.nodes._context import format_chunks
from app.graph.parts.d_part.schemas import DPartGraphState, get_active_query
from app.rag.retrievers.d_part import DPartRetriever

retriever = DPartRetriever()

# 쿼터/임계값으로도 뒷받침 근거(특히 법령원문)를 못 찾았을 때의 문구. finalize의
# _FALLTHROUGH_MESSAGE("아무 데도 안 걸림")와는 구분 — 여기는 "질의는 받았으나 근거 없음".
# victim_check._FALLBACK_MESSAGE 톤을 따르며, 실질 법률정보가 아니라 면책은 붙이지 않는다.
NO_EVIDENCE_MESSAGE = (
    "질문하신 내용과 관련된 법령이나 판례 자료를 찾지 못했습니다. "
    "정확한 안내를 위해 전문가(변호사·대한법률구조공단 등) 상담을 받아보시길 권해드립니다."
)


async def retrieve_open_context(state: DPartGraphState) -> str | None:
    """전체 검색 결과를 LLM 컨텍스트 문자열로 반환한다.

    근거가 될 법령원문이 없으면 state를 '근거 없음' 응답으로 확정하고 None을 반환한다 —
    호출부는 그대로 return해 응답 생성을 건너뛴다.
    """
    chunks = await retriever.search_balanced(get_active_query(state))
    state["retrieved_chunks"] = chunks

    if not any(c.source_type == "법령원문" for c in chunks):
        # 판례/HUG만 걸렸어도 근거 카드(META)를 내보내면 '근거 없음' 메시지와 모순되므로 비운다(단위 46).
        state["retrieved_chunks"] = []
        state["final_answer"] = NO_EVIDENCE_MESSAGE
        return None

    return format_chunks(chunks)
