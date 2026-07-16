"""
미인지형/인지형 판별 로직 (결합형 슬롯 채우기).

1. 사용자가 상황을 자유 서술
2. LLM이 전세사기피해자법 요건 슬롯에 매핑 (schemas.py 참고)
3. 불명확한 슬롯만 추가 질문으로 보완
4. 모든 슬롯 충족 확인 시 구제수단보유여부를 명시적으로 질문 후 판단 결과 제공 (높음/있음/추가확인)
   반복 질문에도 안 채워지면 Fallback(전문가 상담 안내)
"""
from app.graph.parts.d_part.nodes._confirmation import parse_confirmation
from app.graph.parts.d_part.schemas import DPartGraphState, SlotStatus, VictimJudgment, VictimRequirementSlots
from app.llm import d_part as llm_d_part

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


async def _extract_slots(user_input: str, existing: VictimRequirementSlots) -> VictimRequirementSlots:
    """이번 턴 발화에서 새로 확인된 슬롯 값만 LLM으로 추출한다. 기존 슬롯은 참고 컨텍스트로만
    넘기고, 기존 값과의 병합은 _merge_slots가 코드로 수행한다 — 프롬프트에 병합을 맡기면
    모델이 지시를 어겼을 때 이미 filled였던 슬롯이 unclear로 회귀해 같은 질문을 다시 묻는다.
    has_relief_measure는 이 호출이 건드리지 않는 필드다(명시 확인질문 전용)."""
    result = await llm_d_part.call_victim_check(user_input, existing_slots=existing.model_dump(mode="json"))
    return VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus(result["moved_in_and_fixed_date"]),
        deposit_under_limit=SlotStatus(result["deposit_under_limit"]),
        multiple_victims=SlotStatus(result["multiple_victims"]),
        no_intent_to_return=SlotStatus(result["no_intent_to_return"]),
        multiple_victims_reason=result.get("multiple_victims_reason"),
        auction_completed=result.get("auction_completed"),
    )


def _merge_slots(existing: VictimRequirementSlots, extracted: VictimRequirementSlots) -> VictimRequirementSlots:
    """기존 슬롯 위에 이번 턴 추출값을 얹는다. 병합은 비즈니스 판단이라 코드가 결정한다.

    - filled는 되돌리지 않는다 — 이후 턴의 unclear/unfilled로 덮어쓰지 않음.
    - auction_completed는 True로만 올라가고 내려오지 않는다. 매 턴 LLM이 재판정하므로
      False/None으로 덮어쓰면 슬롯①③ 면제가 뒤집혀 판정이 통째로 바뀐다.
    - has_relief_measure는 여기서 절대 안 건드린다(명시 확인질문 전용).
    - multiple_victims_reason은 새 근거가 없으면 기존 근거를 남긴다.
    """
    merged = existing.model_copy()
    for name in _SLOT_ORDER:
        if getattr(existing, name) == SlotStatus.FILLED:
            continue
        extracted_value = getattr(extracted, name)
        if extracted_value is not None:
            setattr(merged, name, extracted_value)

    if extracted.auction_completed is True:
        merged.auction_completed = True
    if extracted.multiple_victims_reason is not None:
        merged.multiple_victims_reason = extracted.multiple_victims_reason

    return merged


def _unresolved_required_slots(slots: VictimRequirementSlots) -> list[str]:
    exempt = _AUCTION_EXEMPT_SLOTS if slots.auction_completed else set()
    return [
        name
        for name in _SLOT_ORDER
        if name not in exempt and getattr(slots, name) in (None, SlotStatus.UNCLEAR)
    ]


def _compute_judgment(slots: VictimRequirementSlots) -> VictimJudgment:
    """요건충족 임계값 판단은 의도적으로 규칙기반 유지(필수슬롯 전부 FILLED면 높음,
    하나라도 UNFILLED면 추가확인) — 법적 요건 충족 여부는 결정론적으로 판단하는 게 맞다는 설계 결정.
    '있음'(PRESENT) 단계 산출은 범위 밖(2026-07-11 확정)."""
    exempt = _AUCTION_EXEMPT_SLOTS if slots.auction_completed else set()
    required_values = [getattr(slots, name) for name in _SLOT_ORDER if name not in exempt]
    if all(v == SlotStatus.FILLED for v in required_values):
        return VictimJudgment.HIGH
    return VictimJudgment.NEEDS_CONFIRMATION


async def check_victim_status(state: DPartGraphState) -> DPartGraphState:
    """요건 슬롯 판별 + 구제수단 확인 + 최종판단 상태기계.
    이미 final_answer가 세팅된 턴(예: stage_router 확인질문 대기 중)은 건드리지 않고 통과한다.

    종결(판정 확정/지원대상 제외/fallback) 시 victim_flow_closed를 세우면 supervisor가
    이후 턴을 정상 재분류하므로, 이 노드로 다시 라우팅됐다는 건 supervisor가 이번 턴 발화를
    victim_interview로 재분류했다는 뜻이다. 이때는 기존 슬롯을 그대로 둔 채 종결 표식만
    되돌려 인터뷰를 이어간다 — 처음부터 다시 묻지 않는다(설계 결정).
    """
    if state.get("final_answer") is not None:
        return state

    if state.get("victim_flow_closed"):
        state["victim_flow_closed"] = False
        state["victim_judgment"] = None
        state["victim_fallback"] = False
        state["victim_check_attempts"] = 0

    user_input = state["user_input"]
    slots = state.get("victim_slots") or VictimRequirementSlots()

    if state.get("awaiting_relief_confirmation"):
        answer = await parse_confirmation(_RELIEF_QUESTION, user_input)
        if answer is None:
            # 예/아니오로 확신할 수 없는 응답 — 절대 긍정으로 삼키지 않는다(부당 제외 방지).
            # 재질문만 반복하면 무한루프가 되므로 상한에 걸어 fallback으로 내보낸다.
            attempts = state.get("victim_check_attempts", 0) + 1
            state["victim_check_attempts"] = attempts
            state["victim_slots"] = slots
            if attempts >= _MAX_ATTEMPTS:
                state["awaiting_relief_confirmation"] = False
                state["victim_fallback"] = True
                state["victim_flow_closed"] = True
                state["final_answer"] = _FALLBACK_MESSAGE
            else:
                state["final_answer"] = _RELIEF_QUESTION
            return state
        slots.has_relief_measure = answer
        state["awaiting_relief_confirmation"] = False
    else:
        before = slots.model_copy()
        extracted = await _extract_slots(user_input, slots)
        slots = _merge_slots(slots, extracted)
        made_progress = slots != before
        state["victim_check_attempts"] = 0 if made_progress else state.get("victim_check_attempts", 0) + 1

    state["victim_slots"] = slots

    unresolved = _unresolved_required_slots(slots)
    if unresolved:
        if state.get("victim_check_attempts", 0) >= _MAX_ATTEMPTS:
            state["victim_fallback"] = True
            state["victim_flow_closed"] = True
            state["final_answer"] = _FALLBACK_MESSAGE
        else:
            state["final_answer"] = _SLOT_QUESTIONS[unresolved[0]]
        return state

    if slots.has_relief_measure is None:
        state["awaiting_relief_confirmation"] = True
        # 슬롯 단계에서 누적된 카운터를 넘겨받지 않도록 초기화 — 게이트는 자기 몫의 상한을 갖는다
        state["victim_check_attempts"] = 0
        state["final_answer"] = _RELIEF_QUESTION
        return state

    if slots.has_relief_measure:
        state["final_answer"] = _EXCLUSION_MESSAGE
        state["disclaimer_required"] = True  # 지원대상 제외 판정(법률 정보) → finalize가 면책 첨부
        state["victim_judgment"] = None
        state["victim_flow_closed"] = True
    else:
        state["victim_judgment"] = _compute_judgment(slots)
        state["victim_flow_closed"] = True
        state["needs_response_assembly"] = True
        state["final_answer"] = None
    return state
