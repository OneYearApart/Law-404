"""
특수상황(인지형) 매칭 노드.
이미 피해자임을 인지한 사용자를 위한 개괄 수준 지원절차 안내.
1. 임대인 사망/파산
2. 신탁사기
3. 다가구주택
4. 공인중개사 허위고지
"""
from app.graph.parts.d_part.schemas import DPartGraphState, get_active_query
from app.llm import d_part as llm_d_part

_SPECIAL_CASE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "임대인 사망/파산": ("임대인이 사망", "집주인이 사망", "임대인이 파산", "집주인이 파산", "상속인"),
    "신탁사기": ("신탁", "수탁자", "신탁사기"),
    "다가구주택": ("다가구", "다가구주택", "선순위 보증금"),
    "공인중개사 허위고지": ("공인중개사가 거짓말", "중개사가 허위", "중개사가 숨기고", "공인중개사 허위고지", "중개사가 말 안 해줬"),
}

_SPECIAL_CASE_GUIDANCE: dict[str, str] = {
    "임대인 사망/파산": (
        "임대인이 사망하거나 파산한 경우, 상속인 또는 파산관재인을 상대로 보증금 반환을 청구할 수 있습니다. "
        "경매·공매 절차에서는 우선매수권 및 경공매 유예 제도를 활용할 수 있는지 확인이 필요합니다. "
        "구체적인 절차는 관할 법원 및 법률구조공단 상담을 통해 확인하시길 권해드립니다."
    ),
    "신탁사기": (
        "신탁된 부동산은 등기부상 소유자가 수탁자(신탁회사)로 되어 있어 임대인이 실제 소유자가 아닐 수 있습니다. "
        "신탁원부를 확인해 임대인이 임대 권한을 위임받았는지 확인하는 것이 중요하며, "
        "조세채권 안분 등 관련 구제 절차 상담이 필요합니다."
    ),
    "다가구주택": (
        "다가구주택은 여러 세대가 하나의 건물에 거주해 선순위 보증금이 많을 경우 배당 순위에서 불리할 수 있습니다. "
        "등기부등본과 확정일자 순위를 통해 선순위 임차인 현황을 확인하시길 권해드립니다."
    ),
    "공인중개사 허위고지": (
        "공인중개사가 중요사항을 허위 또는 누락 고지한 경우, 공인중개사법에 따라 손해배상을 청구할 수 있습니다. "
        "중개대상물 확인설명서와 계약 당시 정황을 근거자료로 확보해두시길 권해드립니다."
    ),
}


async def _llm_special_case_check(user_input: str) -> str | None:
    """1단계 키워드 스캔이 못 잡은 애매한 케이스를 LLM으로 보완 판별한다."""
    result = await llm_d_part.call_special_cases(user_input)
    return result.get("category")


async def match_special_case(state: DPartGraphState) -> DPartGraphState:
    """4개 특수상황 카테고리 중 하나에 해당하는지 판단한다(키워드 1차 스캔 + LLM 2차 보완).
    이미 매칭된 상태(special_case_matched가 값이 있음)면 재판정하지 않고 통과한다.
    이미 final_answer가 세팅된 턴(예: stage_router 확인질문 대기 중)도 건드리지 않고 통과한다."""
    if state.get("final_answer") is not None:
        return state
    if state.get("special_case_matched"):
        return state

    user_input = get_active_query(state)

    for category, keywords in _SPECIAL_CASE_KEYWORDS.items():
        if any(kw in user_input for kw in keywords):
            state["special_case_matched"] = category
            state["final_answer"] = _SPECIAL_CASE_GUIDANCE[category]
            return state

    category = await _llm_special_case_check(user_input)
    if category:
        state["special_case_matched"] = category
        state["final_answer"] = _SPECIAL_CASE_GUIDANCE[category]
        return state

    state["special_case_matched"] = None
    return state
