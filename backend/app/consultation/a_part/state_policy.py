"""슬롯 상태를 위험 수준·보류 행동·추가 질문에 반영한다."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.consultation.a_part.issues import get_issue_definition
from app.consultation.a_part.models import (
    ConversationState,
    SlotState,
    SlotStatus,
)
from app.consultation.a_part.question_builder import FollowUpQuestion
from typing import Any


HIGH_RISK_ISSUES = {
    "q01_owner_proxy",
    "q02_co_owner",
    "q03_owner_lessor_mismatch",
    "q04_broker_account_payment",
    "q05_account_change_before_contract",
    "q06_broker_explanation_mismatch",
    "q07_mortgage",
    "q08_multiunit_priority",
    "q09_registry_restriction_warning",
    "q10_trust",
    "q14_special_clause_deposit_return",
    "q18_address_mismatch",
    "q19_deposit_transfer_mismatch",
}

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

ISSUE_HOLD_ACTIONS: dict[str, tuple[str, ...]] = {
    "q01_owner_proxy": ("계약서 서명 또는 계약 진행", "계약금 또는 잔금 송금"),
    "q02_co_owner": ("계약서 서명 또는 계약 진행", "계약금 또는 잔금 송금"),
    "q03_owner_lessor_mismatch": ("계약서 서명 또는 계약 진행", "계약금 또는 잔금 송금"),
    "q04_broker_account_payment": ("계약금 송금",),
    "q05_account_change_before_contract": ("계약금 또는 잔금 송금",),
    "q06_broker_explanation_mismatch": ("정정 전 계약서 서명 또는 계약 진행",),
    "q07_mortgage": ("확인 전 계약서 서명 또는 계약 진행", "계약금 또는 잔금 송금"),
    "q08_multiunit_priority": ("확인 전 계약서 서명 또는 계약 진행", "계약금 또는 잔금 송금"),
    "q09_registry_restriction_warning": ("계약서 서명 또는 계약 진행", "계약금 또는 잔금 송금"),
    "q10_trust": ("계약서 서명 또는 계약 진행", "계약금 또는 잔금 송금"),
    "q14_special_clause_deposit_return": ("특약 정정 전 계약서 서명 또는 계약 진행", "계약금 송금"),
    "q18_address_mismatch": ("주소 확인·정정 전 계약서 서명", "계약금 또는 잔금 송금"),
    "q19_deposit_transfer_mismatch": ("차액 확인 전 추가 송금 또는 잔금 지급",),
}


class ConversationRiskAssessment(BaseModel):
    risk_level: str
    core_judgment: str
    hold_actions: list[str] = Field(default_factory=list, max_length=3)
    unresolved_critical_labels: list[str] = Field(default_factory=list)
    conflict_labels: list[str] = Field(default_factory=list)


def _bool_false_requires_confirmation(slot: SlotState) -> bool:
    if slot.value is not False:
        return False
    return (
        slot.key in TRUE_REQUIRED_KEYS
        or slot.key.endswith(TRUE_REQUIRED_SUFFIXES)
    )


def _is_unresolved_critical(slot: SlotState) -> bool:
    if not slot.risk_critical:
        return False
    if slot.status in {
        SlotStatus.UNKNOWN,
        SlotStatus.UNCERTAIN,
        SlotStatus.CONFLICT,
    }:
        return True
    if slot.status == SlotStatus.NOT_APPLICABLE:
        return False
    if slot.value is None:
        return True
    if isinstance(slot.value, str) and not slot.value.strip():
        return True
    if _bool_false_requires_confirmation(slot):
        return True
    return False


def _unique(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


def _hold_actions_for_state(state: ConversationState) -> list[str]:
    actions: list[str] = []
    for issue_id in state.all_issue_ids:
        actions.extend(ISSUE_HOLD_ACTIONS.get(issue_id, ()))
    return _unique(actions)[:3]


def evaluate_conversation_risk(
    state: ConversationState,
) -> ConversationRiskAssessment:
    conflict_labels: list[str] = []
    unresolved_labels: list[str] = []

    for issue_id in state.all_issue_ids:
        issue = get_issue_definition(issue_id)
        for slot in state.issue_slots.get(issue_id, {}).values():
            label = f"[{issue.name}] {slot.label}"
            if slot.status == SlotStatus.CONFLICT:
                conflict_labels.append(label)
            if _is_unresolved_critical(slot):
                unresolved_labels.append(label)

    conflict_labels = _unique(conflict_labels)
    unresolved_labels = _unique(unresolved_labels)
    has_high_risk_issue = any(
        issue_id in HIGH_RISK_ISSUES
        for issue_id in state.all_issue_ids
    )

    if conflict_labels:
        labels = ", ".join(conflict_labels[:3])
        return ConversationRiskAssessment(
            risk_level="진행 보류 권장" if has_high_risk_issue else "확인 필요",
            core_judgment=(
                f"앞서 확인한 내용과 새 답변이 충돌하는 항목이 있습니다: {labels}. "
                "자료나 실제 표시 내용을 다시 확인하기 전에는 기존 판단을 확정하지 않습니다."
            ),
            hold_actions=(
                _hold_actions_for_state(state)
                if has_high_risk_issue
                else []
            ),
            unresolved_critical_labels=unresolved_labels,
            conflict_labels=conflict_labels,
        )

    if unresolved_labels:
        labels = ", ".join(unresolved_labels[:3])
        return ConversationRiskAssessment(
            risk_level=(
                "진행 보류 권장"
                if has_high_risk_issue
                else "확인 필요"
            ),
            core_judgment=(
                f"현재 답변에서 일부 사실은 확인됐지만 핵심 확인 항목이 남아 있습니다: {labels}. "
                "남은 항목을 확인한 뒤 위험 수준과 다음 행동을 다시 판단해야 합니다."
            ),
            hold_actions=(
                _hold_actions_for_state(state)
                if has_high_risk_issue
                else []
            ),
            unresolved_critical_labels=unresolved_labels,
            conflict_labels=[],
        )

    if has_high_risk_issue:
        return ConversationRiskAssessment(
            risk_level="확인 필요",
            core_judgment=(
                "현재 답변 기준으로 위험 판단에 필요한 핵심 확인 항목은 모두 채워졌습니다. "
                "다만 입력한 사실이 실제 문서와 일치하는지 확인하기 전에는 계약의 안전을 확정할 수 없습니다."
            ),
            hold_actions=[],
            unresolved_critical_labels=[],
            conflict_labels=[],
        )

    return ConversationRiskAssessment(
        risk_level="현재 입력 기준 중대한 보류 사유 미확인",
        core_judgment=(
            "현재 답변 기준으로 핵심 확인 항목은 모두 채워졌습니다. "
            "남은 일반 절차와 실제 문서 내용을 확인해 상담을 마무리하세요."
        ),
        hold_actions=[],
        unresolved_critical_labels=[],
        conflict_labels=[],
    )


def apply_state_policy_to_response(
    response: Any,
    *,
    state: ConversationState,
    follow_up_questions: list[FollowUpQuestion],
) -> tuple[Any, ConversationRiskAssessment]:
    """기존 RAG 근거와 참고 자료는 유지하고 상태에 따라 답변 부분만 갱신한다."""

    assessment = evaluate_conversation_risk(state)
    data = response.model_dump(mode="python")
    answer = data["answer"]

    generation_status = data.get("generation_status", "completed")
    if hasattr(generation_status, "value"):
        generation_status = generation_status.value
    failed_generation = generation_status in {
        "evidence_not_found",
        "search_failed",
        "generation_failed",
        "validation_failed",
    }

    answer["risk_level"] = assessment.risk_level
    if not failed_generation:
        answer["core_judgment"] = assessment.core_judgment
    answer["hold_actions"] = assessment.hold_actions[:3]
    answer["follow_up_questions"] = [
        item.question
        for item in follow_up_questions[:3]
    ]

    required_information = list(answer.get("required_information") or [])
    required_information = _unique(
        [
            *assessment.conflict_labels,
            *assessment.unresolved_critical_labels,
            *required_information,
        ]
    )
    answer["required_information"] = required_information[:6]

    updated = response.__class__.model_validate(data)
    return updated, assessment
