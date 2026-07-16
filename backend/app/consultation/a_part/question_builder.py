"""현재 슬롯 상태에서 남은 추가 질문과 상담 문맥을 만든다."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.consultation.a_part.issues import get_issue_definition
from app.consultation.a_part.models import (
    ConversationState,
    FactSource,
    SlotState,
    SlotStatus,
)


TRUE_REQUIRED_SUFFIXES = (
    "_confirmed",
    "_checked",
    "_completed",
    "_received",
    "_kept",
    "_planned",
    "_available",
    "_effective",
    "_agreed",
    "_identified",
)

TRUE_REQUIRED_KEYS = {
    "owner_direct_confirmation",
    "absent_co_owner_consent",
    "new_account_payment_authority",
    "written_change_record",
    "trustee_consent_confirmed",
    "payment_proof_available",
    "reporting_required_confirmed",
}


class QuestionOption(BaseModel):
    label: str
    answer_text: str


class FollowUpQuestion(BaseModel):
    issue_id: str
    slot_key: str
    question_key: str | None = None
    label: str
    question: str
    status: SlotStatus
    risk_critical: bool
    input_type: str = "text"
    options: list[QuestionOption] = Field(default_factory=list)
    allow_custom_input: bool = True
    placeholder: str | None = None




def _question_ui(slot: SlotState) -> tuple[str, list[QuestionOption], bool, str | None]:
    """질문 문장과 슬롯 특성으로 프론트 입력 방식을 결정한다."""

    asks_for_value = any(
        marker in slot.question
        for marker in ("누구", "언제", "얼마", "무엇", "어디", "어떤", "어떻게")
    )
    boolean_question = not asks_for_value and (
        slot.key.endswith((
            "_confirmed",
            "_checked",
            "_completed",
            "_received",
            "_kept",
            "_planned",
            "_available",
            "_effective",
            "_agreed",
            "_exists",
        ))
        or slot.question.endswith(("나요?", "있나요?", "했나요?", "인가요?"))
    )

    if boolean_question:
        return (
            "single_choice",
            [
                QuestionOption(label="네, 확인했어요", answer_text="네, 확인했습니다."),
                QuestionOption(label="아니요, 아직이에요", answer_text="아니요, 아직 확인하지 못했습니다."),
                QuestionOption(label="잘 모르겠어요", answer_text="잘 모르겠습니다."),
            ],
            True,
            "직접 답변을 입력할 수도 있습니다.",
        )

    if slot.key in {"payment_account_holder", "receiving_account_holders"}:
        return (
            "single_choice",
            [
                QuestionOption(label="소유자 본인", answer_text="소유자 본인 명의입니다."),
                QuestionOption(label="대리인", answer_text="대리인 명의입니다."),
                QuestionOption(label="중개사무소", answer_text="중개사무소 명의입니다."),
                QuestionOption(label="제3자", answer_text="제3자 명의입니다."),
                QuestionOption(label="잘 모르겠어요", answer_text="예금주를 아직 확인하지 못했습니다."),
            ],
            True,
            "예금주 이름을 직접 입력해 주세요.",
        )

    if slot.key == "contract_change_type":
        return (
            "single_choice",
            [
                QuestionOption(label="신규 계약", answer_text="신규 계약입니다."),
                QuestionOption(label="갱신 계약", answer_text="갱신 계약입니다."),
                QuestionOption(label="잘 모르겠어요", answer_text="신규 계약인지 갱신 계약인지 잘 모르겠습니다."),
            ],
            False,
            None,
        )

    if slot.key == "housing_type":
        return (
            "single_choice",
            [
                QuestionOption(label="아파트", answer_text="아파트입니다."),
                QuestionOption(label="연립·다세대", answer_text="연립 또는 다세대주택입니다."),
                QuestionOption(label="다가구", answer_text="다가구주택입니다."),
                QuestionOption(label="오피스텔", answer_text="오피스텔입니다."),
                QuestionOption(label="잘 모르겠어요", answer_text="주택 유형을 아직 확인하지 못했습니다."),
            ],
            True,
            "다른 주택 유형을 직접 입력해 주세요.",
        )

    if slot.key == "guarantee_provider":
        return (
            "single_choice",
            [
                QuestionOption(label="HUG", answer_text="HUG 반환보증을 검토하고 있습니다."),
                QuestionOption(label="HF", answer_text="HF 반환보증을 검토하고 있습니다."),
                QuestionOption(label="SGI", answer_text="SGI 반환보증을 검토하고 있습니다."),
                QuestionOption(label="아직 미정", answer_text="보증기관은 아직 정하지 않았습니다."),
            ],
            True,
            "다른 기관을 직접 입력해 주세요.",
        )

    return "text", [], True, f"{slot.label} 내용을 입력해 주세요."


def _display_value(value: object) -> str:
    if value is True:
        return "예"
    if value is False:
        return "아니요"
    if value is None:
        return "값 없음"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _confirmed_false_needs_follow_up(slot: SlotState) -> bool:
    return (
        slot.status == SlotStatus.CONFIRMED
        and slot.value is False
        and (
            slot.key in TRUE_REQUIRED_KEYS
            or slot.key.endswith(TRUE_REQUIRED_SUFFIXES)
        )
    )


def _slot_needs_question(slot: SlotState) -> bool:
    # 사용자가 "잘 모르겠어요"라고 답한 경우에는 사실 자체는 미확인이지만
    # 해당 질문에는 응답한 것으로 본다. 같은 질문을 반복하지 않고 최종
    # 위험 판단의 미확인 사유로 남긴다. 문서 분석에서 생긴 uncertain은
    # 사용자의 직접 확인이 필요하므로 계속 질문 후보로 유지한다.
    if (
        slot.status == SlotStatus.UNCERTAIN
        and slot.source == FactSource.USER
    ):
        return False

    # 부정 답변도 사용자가 확인해 준 사실이다. 같은 질문을 반복하지 않고
    # 최종 위험 판단에서 보류 사유로 사용한다.
    return slot.is_missing()


def _slot_question_text(slot: SlotState) -> str:
    if slot.status == SlotStatus.CONFLICT:
        return (
            f"앞서 답한 ‘{slot.label}’ 내용이 서로 다릅니다. "
            f"자료를 다시 확인한 뒤 답해 주세요. {slot.question}"
        )

    if slot.status == SlotStatus.UNCERTAIN:
        return (
            f"‘{slot.label}’이 아직 명확하지 않습니다. "
            f"{slot.question}"
        )

    if _confirmed_false_needs_follow_up(slot):
        return (
            f"‘{slot.label}’이 아직 충족되지 않았습니다. "
            f"{slot.question}"
        )

    return slot.question


def _iter_question_candidates(
    state: ConversationState,
) -> list[tuple[str, SlotState]]:
    candidates: list[tuple[str, SlotState]] = []
    for issue_id in state.all_issue_ids:
        for slot in state.issue_slots.get(issue_id, {}).values():
            if _slot_needs_question(slot):
                candidates.append((issue_id, slot))
    return candidates


def build_follow_up_questions(
    state: ConversationState,
    *,
    max_questions: int = 1,
    mark_as_asked: bool = True,
) -> list[FollowUpQuestion]:
    """conflict와 위험 핵심 슬롯을 우선해 질문 한 개만 반환한다."""

    if max_questions < 0:
        raise ValueError("max_questions는 0 이상이어야 합니다.")
    if max_questions == 0:
        return []

    candidates: list[tuple[tuple[object, ...], str, SlotState]] = []
    asked = set(state.asked_question_keys)

    for issue_id, slot in _iter_question_candidates(state):
        question_key = f"{issue_id}:{slot.key}"
        status_rank = {
            SlotStatus.CONFLICT: 0,
            SlotStatus.UNCERTAIN: 1,
            SlotStatus.UNKNOWN: 2,
            SlotStatus.CONFIRMED: 2,
        }.get(slot.status, 3)

        sort_key = (
            status_rank,
            not slot.risk_critical,
            question_key in asked,
            slot.priority,
            issue_id,
            slot.key,
        )
        candidates.append((sort_key, issue_id, slot))

    candidates.sort(key=lambda item: item[0])

    result = [
        FollowUpQuestion(
            issue_id=issue_id,
            slot_key=slot.key,
            question_key=f"{issue_id}:{slot.key}",
            label=slot.label,
            question=_slot_question_text(slot),
            status=slot.status,
            risk_critical=slot.risk_critical,
            input_type=_question_ui(slot)[0],
            options=_question_ui(slot)[1],
            allow_custom_input=_question_ui(slot)[2],
            placeholder=_question_ui(slot)[3],
        )
        for _, issue_id, slot in candidates[:max_questions]
    ]

    if mark_as_asked:
        state.active_question_key = result[0].question_key if result else None
        for item in result:
            if item.question_key not in state.asked_question_keys:
                state.asked_question_keys.append(item.question_key)
        state.touch()

    return result


def confirmed_fact_sentences(
    state: ConversationState,
    *,
    max_items: int = 10,
) -> list[str]:
    """RAG ConsultationContext에 넣을 확인 사실을 사람이 읽는 문장으로 만든다."""

    items: list[tuple[tuple[object, ...], str]] = []

    for issue_id in state.all_issue_ids:
        issue = get_issue_definition(issue_id)
        for slot in state.issue_slots.get(issue_id, {}).values():
            if slot.status == SlotStatus.CONFIRMED:
                display_value = _display_value(slot.value)
            elif (
                slot.status == SlotStatus.UNCERTAIN
                and slot.source == FactSource.USER
            ):
                display_value = "확인하지 못함"
            elif slot.status == SlotStatus.NOT_APPLICABLE:
                display_value = "현재 상황에 적용되지 않음"
            else:
                continue
            sentence = (
                f"[{issue.name}] {slot.label}: {display_value}"
            )
            sort_key = (
                not slot.risk_critical,
                slot.priority,
                issue_id,
                slot.key,
            )
            items.append((sort_key, sentence))

    items.sort(key=lambda item: item[0])
    return [sentence for _, sentence in items[:max_items]]


def missing_fact_labels(state: ConversationState) -> list[str]:
    result: list[str] = []
    for issue_id, slot in _iter_question_candidates(state):
        issue = get_issue_definition(issue_id)
        result.append(f"[{issue.name}] {slot.label}")
    return result


def conflict_fact_labels(state: ConversationState) -> list[str]:
    result: list[str] = []
    for issue_id in state.all_issue_ids:
        issue = get_issue_definition(issue_id)
        for slot in state.issue_slots.get(issue_id, {}).values():
            if slot.status == SlotStatus.CONFLICT:
                values = ", ".join(
                    _display_value(value)
                    for value in slot.conflicting_values
                )
                result.append(
                    f"[{issue.name}] {slot.label}: {values or '서로 다른 답변'}"
                )
    return result
