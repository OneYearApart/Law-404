"""
topic이 없는 두 경로(open_qa / recognized_general)가 공유하는 전체 검색.

둘 다 미리 정해진 topic_tag가 없어 전체 임베딩 테이블을 훑는다(단위 28: search_balanced —
source_type 쿼터 + distance 임계값으로 균형을 맞춰, 한 종류(주로 판례)가 컨텍스트를 독점해
조문이 없는데도 해설·상황적용을 지어내던 문제를 막는다).

뒷받침할 법령원문을 못 찾으면 억지 생성 대신 '근거 없음'으로 빠지는 규칙도 함께 공유한다.
한쪽에만 두면 다른 쪽이 조용히 조문을 지어낸다 — 두 경로가 같은 검색을 쓰는 이상 이 규칙은
경로가 아니라 검색에 딸린 것이다.

topic_tag가 있는 경로(general_scenario/special_cases)는 항목 라벨이 법률 어휘를 쿼리에 실어주지만,
이 두 경로엔 그게 없어 사용자 구어가 그대로 임베딩된다. 그래서 검색 전에만 질의를 법률 어휘로
확장한다(call_query_expansion). 확장 결과는 검색에만 쓰고 생성 컨텍스트엔 원문 발화를 넣는다 —
모델이 답해야 할 건 사용자가 실제로 한 말이지 기계가 다듬은 질의가 아니다.
"""

import logging

from app.graph.parts.d_part.nodes._context import build_context
from app.graph.parts.d_part.schemas import DPartGraphState
from app.llm import d_part as llm_d_part
from app.rag.retrievers.d_part import DPartRetriever

logger = logging.getLogger(__name__)

retriever = DPartRetriever()

# 쿼터/임계값으로도 뒷받침 근거(특히 법령원문)를 못 찾았을 때의 문구. finalize의
# _FALLTHROUGH_MESSAGE("아무 데도 안 걸림")와는 구분 — 여기는 "질의는 받았으나 근거 없음".
# victim_check._FALLBACK_MESSAGE 톤을 따르며, 실질 법률정보가 아니라 면책은 붙이지 않는다.
NO_EVIDENCE_MESSAGE = (
    "질문하신 내용과 관련된 법령이나 판례 자료를 찾지 못했습니다. "
    "정확한 안내를 위해 전문가(변호사·대한법률구조공단 등) 상담을 받아보시길 권해드립니다."
)


async def _search_query(user_input: str) -> str:
    """검색에 쓸 질의 — 확장에 실패하면 원문 발화로 검색한다.
    확장은 검색 품질 개선일 뿐이라, 실패했다고 턴을 통째로 죽이는 건 과한 대가다."""
    try:
        expanded = await llm_d_part.call_query_expansion(user_input)
    except Exception:
        logger.warning("검색 질의 확장 실패 — 원문 발화로 검색한다", exc_info=True)
        return user_input
    return expanded or user_input


async def retrieve_open_context(state: DPartGraphState) -> str | None:
    """전체 검색 결과를 LLM 컨텍스트 문자열로 반환한다.

    근거가 될 법령원문이 없으면 state를 '근거 없음' 응답으로 확정하고 None을 반환한다 —
    호출부는 그대로 return해 응답 생성을 건너뛴다.
    """
    chunks = await retriever.search_balanced(await _search_query(state["user_input"]))
    state["retrieved_chunks"] = chunks

    if not any(c.source_type == "법령원문" for c in chunks):
        # 판례/HUG만 걸렸어도 근거 카드(META)를 내보내면 '근거 없음' 메시지와 모순되므로 비운다(단위 46).
        state["retrieved_chunks"] = []
        state["final_answer"] = NO_EVIDENCE_MESSAGE
        return None

    # 컨텍스트엔 확장 질의가 아니라 원문 발화를 넣는다(위 모듈 주석 참고)
    return build_context(chunks, query=state["user_input"])
