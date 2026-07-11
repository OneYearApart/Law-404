"""
미인지형/인지형 판별 로직 (결합형 슬롯 채우기).

1. 사용자가 상황을 자유 서술
2. LLM이 전세사기피해자법 요건 슬롯에 매핑 (schemas.py 참고)
3. 불명확한 슬롯만 추가 질문으로 보완
4. 모든 슬롯 충족 확인 시 구제수단보유여부를 명시적으로 질문 후 판단 결과 제공 (높음/있음/추가확인)
   반복 질문에도 안 채워지면 Fallback(전문가 상담 안내)
"""
import re

from app.graph.parts.d_part.nodes.stage_router import _CONFIRM_NO, _CONFIRM_YES
from app.graph.parts.d_part.schemas import DPartGraphState, SlotStatus, VictimJudgment, VictimRequirementSlots

_SLOT_ORDER = ("moved_in_and_fixed_date", "deposit_under_limit", "multiple_victims", "no_intent_to_return")
_AUCTION_EXEMPT_SLOTS = {"moved_in_and_fixed_date", "multiple_victims"}
_MAX_ATTEMPTS = 3

_SLOT_QUESTIONS = {
    "moved_in_and_fixed_date": "전입신고와 확정일자를 받아두셨나요? (또는 임차권등기, 전세권 설정 여부)",
    "deposit_under_limit": "보증금은 얼마인가요?",
    "multiple_victims": "같은 임대인에게 다른 세입자도 피해를 입었거나 입을 것으로 보이시나요?",
    "no_intent_to_return": "임대인이 보증금을 돌려줄 의사가 없어 보이는 구체적인 정황이 있으신가요?",
}
_RELIEF_QUESTION = (
    "보증보험에 가입되어 있거나, 최우선변제 대상이거나, "
    "대항력·우선변제권으로 이미 보증금을 회수할 수 있는 상황인가요?"
)
_EXCLUSION_MESSAGE = (
    "이미 보증보험, 최우선변제, 또는 대항력·우선변제권을 통해 보증금을 회수할 수 있는 상황으로 확인되어, "
    "전세사기피해자 지원 대상에서는 제외될 수 있습니다. 다만 다른 구제 절차는 이용 가능할 수 있으니 "
    "관련 상담을 받아보시길 권해드립니다."
)
_FALLBACK_MESSAGE = (
    "죄송하지만 말씀해주신 내용만으로는 요건 충족 여부를 판단하기 어렵습니다. "
    "정확한 상담을 위해 전문가(변호사·법률구조공단 등) 상담을 받아보시길 권해드립니다."
)


async def _mock_extract_slots(user_input: str, existing: VictimRequirementSlots) -> VictimRequirementSlots:
    """실제 GPT-4o 연동 전까지 쓰는 키워드 기반 mock 슬롯 추출기.
    기존 슬롯 값 위에 이번 턴에서 새로 감지된 것만 덮어쓰고, 못 찾으면 기존 값을 유지한다.
    app/llm/d_part.py의 실제 LLM 레이어가 준비되면 이 함수만 교체하면 된다."""
    slots = existing.model_copy()

    if any(kw in user_input for kw in ("경공매가 끝", "경매가 끝", "경공매 완료", "낙찰까지 끝")):
        slots.auction_completed = True

    if any(kw in user_input for kw in ("전입신고 안", "전입신고를 안", "확정일자를 안 받")):
        slots.moved_in_and_fixed_date = SlotStatus.UNFILLED
    elif any(kw in user_input for kw in ("전입신고", "확정일자", "임차권등기", "전세권")):
        slots.moved_in_and_fixed_date = SlotStatus.FILLED

    deposit_match = re.search(r"보증금.{0,10}?(\d+)\s*억", user_input)
    if deposit_match:
        amount = int(deposit_match.group(1))
        slots.deposit_under_limit = SlotStatus.FILLED if amount <= 5 else SlotStatus.UNFILLED

    if any(kw in user_input for kw in ("나 혼자만", "다른 피해자는 없")):
        slots.multiple_victims = SlotStatus.UNFILLED
    elif any(kw in user_input for kw in ("다른 세입자도", "여러 명이", "다수의 피해자", "다른 피해자도")):
        slots.multiple_victims = SlotStatus.FILLED
        slots.multiple_victims_reason = user_input

    if any(kw in user_input for kw in ("곧 돌려준다고", "반환하겠다고")):
        slots.no_intent_to_return = SlotStatus.UNFILLED
    elif any(kw in user_input for kw in ("돌려줄 생각이 없", "반환할 생각이 없", "돌려줄 의사가 없")):
        slots.no_intent_to_return = SlotStatus.FILLED

    return slots


def _unresolved_required_slots(slots: VictimRequirementSlots) -> list[str]:
    exempt = _AUCTION_EXEMPT_SLOTS if slots.auction_completed else set()
    return [
        name
        for name in _SLOT_ORDER
        if name not in exempt and getattr(slots, name) in (None, SlotStatus.UNCLEAR)
    ]


def _compute_mock_judgment(slots: VictimRequirementSlots) -> VictimJudgment:
    """실제로는 GPT-4o의 종합판단 영역 — mock은 단순 규칙만 구현(필수슬롯 전부 FILLED면 높음,
    하나라도 UNFILLED면 추가확인). '있음' 단계는 mock에서 산출하지 않는다.
    app/llm/d_part.py의 실제 LLM 레이어가 준비되면 이 함수만 교체하면 된다."""
    exempt = _AUCTION_EXEMPT_SLOTS if slots.auction_completed else set()
    required_values = [getattr(slots, name) for name in _SLOT_ORDER if name not in exempt]
    if all(v == SlotStatus.FILLED for v in required_values):
        return VictimJudgment.HIGH
    return VictimJudgment.NEEDS_CONFIRMATION


async def check_victim_status(state: DPartGraphState) -> DPartGraphState:
    """요건 슬롯 판별 + 구제수단 확인 + 최종판단 상태기계.
    이미 종결(victim_judgment 확정 또는 victim_fallback)됐으면 재계산하지 않는다."""
    if state.get("victim_judgment") is not None or state.get("victim_fallback"):
        return state

    user_input = state["user_input"]
    slots = state.get("victim_slots") or VictimRequirementSlots()

    if state.get("awaiting_relief_confirmation"):
        if any(kw in user_input for kw in _CONFIRM_YES):
            slots.has_relief_measure = True
            state["awaiting_relief_confirmation"] = False
        elif any(kw in user_input for kw in _CONFIRM_NO):
            slots.has_relief_measure = False
            state["awaiting_relief_confirmation"] = False
        else:
            state["victim_slots"] = slots
            state["final_answer"] = _RELIEF_QUESTION
            return state
    else:
        before = slots.model_copy()
        slots = await _mock_extract_slots(user_input, slots)
        made_progress = slots != before
        state["victim_check_attempts"] = 0 if made_progress else state.get("victim_check_attempts", 0) + 1

    state["victim_slots"] = slots

    unresolved = _unresolved_required_slots(slots)
    if unresolved:
        if state.get("victim_check_attempts", 0) >= _MAX_ATTEMPTS:
            state["victim_fallback"] = True
            state["final_answer"] = _FALLBACK_MESSAGE
        else:
            state["final_answer"] = _SLOT_QUESTIONS[unresolved[0]]
        return state

    if slots.has_relief_measure is None:
        state["awaiting_relief_confirmation"] = True
        state["final_answer"] = _RELIEF_QUESTION
        return state

    if slots.has_relief_measure:
        state["final_answer"] = _EXCLUSION_MESSAGE
        state["victim_judgment"] = None
    else:
        state["victim_judgment"] = _compute_mock_judgment(slots)
        state["final_answer"] = None
    return state
