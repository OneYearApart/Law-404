"""현재 슬롯 상태에서 남은 추가 질문과 상담 문맥을 만든다."""

from __future__ import annotations

from pydantic import BaseModel

from app.consultation.a_part.issues import get_issue_definition
from app.consultation.a_part.models import (
    ConversationState,
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


class FollowUpQuestion(BaseModel):
    issue_id: str
    slot_key: str
    label: str
    question: str
    status: SlotStatus
    risk_critical: bool

    @property
    def question_key(self) -> str:
        return f"{self.issue_id}:{self.slot_key}"


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
    return slot.is_missing() or _confirmed_false_needs_follow_up(slot)


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
    max_questions: int = 3,
    mark_as_asked: bool = True,
) -> list[FollowUpQuestion]:
    """conflict와 위험 핵심 슬롯을 우선해 최대 3개를 반환한다."""

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
            label=slot.label,
            question=_slot_question_text(slot),
            status=slot.status,
            risk_critical=slot.risk_critical,
        )
        for _, issue_id, slot in candidates[:max_questions]
    ]

    if mark_as_asked:
        for item in result:
            if item.question_key not in state.asked_question_keys:
                state.asked_question_keys.append(item.question_key)
        if result:
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
            if slot.status != SlotStatus.CONFIRMED:
                continue
            sentence = (
                f"[{issue.name}] {slot.label}: {_display_value(slot.value)}"
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
