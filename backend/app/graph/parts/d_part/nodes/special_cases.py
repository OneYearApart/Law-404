"""
특수상황(인지형) 실행 노드 — 카테고리 판단은 supervisor가 이미 끝내고
state["special_case_matched"]에 채워 넘긴다. 이 노드는 그 카테고리에 맞는
개괄 안내문을 조회해 final_answer로 채우기만 한다.
1. 임대인 사망/파산
2. 신탁사기
3. 다가구주택
4. 공인중개사 허위고지
"""
from app.graph.parts.d_part.schemas import DPartGraphState

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


async def match_special_case(state: DPartGraphState) -> DPartGraphState:
    """supervisor가 이미 분류한 special_case_matched를 안내문으로 변환한다. 매 턴
    다시 호출돼도(후속 대화가 이어져도) 같은 안내문을 그대로 다시 만든다 — 이 노드엔
    victim_check처럼 이어갈 다회차 상태가 없어서, "이미 매칭됐으니 no-op"으로 두면
    후속 발화가 finalize의 fallthrough 메시지로 빠지는 문제가 있었다(2026-07-14 제거)."""
    if state.get("final_answer") is not None:
        return state

    category = state["special_case_matched"]
    state["final_answer"] = _SPECIAL_CASE_GUIDANCE[category]
    return state
