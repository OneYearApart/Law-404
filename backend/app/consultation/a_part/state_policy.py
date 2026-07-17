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


def _join_korean(items: list[str]) -> str:
    cleaned = _unique([item.strip() for item in items if item and item.strip()])
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]

    previous = cleaned[-2]
    last = previous[-1]
    code = ord(last)
    has_final = 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0
    connector = "과" if has_final else "와"
    return f"{', '.join(cleaned[:-1])}{connector} {cleaned[-1]}"


def _with_particle(text: str, consonant: str, vowel: str) -> str:
    stripped = text.rstrip()
    if not stripped:
        return stripped
    last = stripped[-1]
    code = ord(last)
    has_final = 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0
    return f"{stripped}{consonant if has_final else vowel}"


def _slot_for(
    state: ConversationState,
    issue_id: str,
    slot_key: str,
) -> SlotState | None:
    return state.issue_slots.get(issue_id, {}).get(slot_key)


def _slot_is_confirmed_true(slot: SlotState | None) -> bool:
    return bool(
        slot
        and slot.status == SlotStatus.CONFIRMED
        and slot.value is True
    )


def _slot_is_unresolved(slot: SlotState | None) -> bool:
    if slot is None:
        return True
    if slot.status in {
        SlotStatus.UNKNOWN,
        SlotStatus.UNCERTAIN,
        SlotStatus.CONFLICT,
        SlotStatus.NOT_APPLICABLE,
    }:
        return True
    return slot.status == SlotStatus.CONFIRMED and slot.value is False


def _slot_text(slot: SlotState | None) -> str:
    if slot is None or slot.value is None:
        return ""
    if isinstance(slot.value, list):
        return ", ".join(str(item).strip() for item in slot.value if str(item).strip())
    return str(slot.value).strip()


def _account_text(slot: SlotState | None) -> str:
    value = _slot_text(slot)
    for suffix in ("입니다.", "입니다", "이에요.", "이에요", "예요.", "예요"):
        if value.endswith(suffix):
            value = value[: -len(suffix)].rstrip()
            break
    return value


def _owner_proxy_final_payload(state: ConversationState) -> dict[str, Any]:
    """q01 최종 답변을 실제 슬롯 상태에 맞는 안전한 문장으로 만든다."""

    issue_id = "q01_owner_proxy"
    owner = _slot_for(state, issue_id, "registered_owner_identified")
    intent = _slot_for(state, issue_id, "owner_proxy_intent_confirmed")
    document = _slot_for(state, issue_id, "delegation_document_available")
    scope = _slot_for(state, issue_id, "delegation_scope_confirmed")
    signature = _slot_for(state, issue_id, "signature_authority_confirmed")
    payment = _slot_for(state, issue_id, "payment_authority_confirmed")
    account = _slot_for(state, issue_id, "payment_account_holder")

    confirmed_labels: list[str] = []
    if _slot_is_confirmed_true(intent):
        confirmed_labels.append("소유자의 대리 의사")
    if _slot_is_confirmed_true(scope):
        confirmed_labels.append("계약 체결 범위")
    if _slot_is_confirmed_true(signature):
        confirmed_labels.append("대리인의 서명 권한")
    if _slot_is_confirmed_true(payment):
        confirmed_labels.append("대금 수령 권한")

    unresolved_pairs = [
        (document, "권한을 입증할 위임 자료"),
        (scope, "구체적인 계약 체결 범위"),
        (signature, "대리인의 서명 권한"),
        (payment, "대금 수령 권한"),
    ]
    unresolved_labels = [
        label for slot, label in unresolved_pairs if _slot_is_unresolved(slot)
    ]

    account_value = _account_text(account)
    account_is_owner = any(
        marker in account_value
        for marker in ("소유자 본인", "소유자 명의", "임대인 본인", "임대인 명의")
    )
    account_is_non_owner = bool(account_value) and not account_is_owner

    conclusion_parts: list[str] = []
    confirmed_text = _join_korean(confirmed_labels)
    unresolved_text = _join_korean(unresolved_labels)
    if unresolved_text and confirmed_text:
        conclusion_parts.append(
            f"{_with_particle(confirmed_text, '은', '는')} 확인했지만, "
            f"{_with_particle(unresolved_text, '은', '는')} 확인하지 못했습니다."
        )
    elif unresolved_text:
        conclusion_parts.append(
            f"{_with_particle(unresolved_text, '을', '를')} 확인하지 못했습니다."
        )
    elif confirmed_text:
        conclusion_parts.append(
            f"입력한 답변 기준으로 {_with_particle(confirmed_text, '은', '는')} 확인됐습니다."
        )

    if account_is_non_owner:
        conclusion_parts.append(
            f"계약금 계좌도 소유자 본인 명의가 아닌 {account_value}로 확인됐습니다."
        )

    document_is_confirmed = _slot_is_confirmed_true(document)
    scope_is_unresolved = _slot_is_unresolved(scope)

    if unresolved_labels and account_is_non_owner:
        if document_is_confirmed and scope_is_unresolved:
            conclusion_parts.append(
                "현재 보유한 위임 자료에서 구체적인 계약 체결 범위를 확인하고, "
                "확인한 권한과 계좌 정보를 서로 대조하기 전에는 "
                "계약서 서명과 계약금 송금을 보류하는 것이 안전합니다."
            )
        else:
            conclusion_parts.append(
                "확인한 권한과 계좌 정보를 위임 자료와 대조하기 전에는 "
                "계약서 서명과 계약금 송금을 보류하는 것이 안전합니다."
            )
    elif unresolved_labels:
        if document_is_confirmed and scope_is_unresolved:
            conclusion_parts.append(
                "현재 보유한 위임 자료에서 구체적인 계약 체결 범위를 확인하기 전에는 "
                "계약서 서명을 보류하는 것이 안전합니다."
            )
        else:
            conclusion_parts.append(
                "남은 미확인 권한과 위임 자료를 확인하기 전에는 "
                "계약서 서명을 보류하는 것이 안전합니다."
            )
    elif account_is_non_owner:
        conclusion_parts.append(
            "대리인 명의 계좌의 수령 권한 확인 기록과 위임 자료를 최종 대조한 뒤 진행하세요."
        )
    else:
        conclusion_parts.append(
            "입력한 내용과 실제 위임 자료·계좌 정보가 일치하는지 최종 대조한 뒤 진행하세요."
        )

    owner_name = _slot_text(owner)
    authority_targets: list[str] = []
    if _slot_is_unresolved(scope):
        authority_targets.append("계약 체결 범위")
    if _slot_is_unresolved(signature):
        authority_targets.append("서명 권한")
    if _slot_is_unresolved(payment):
        authority_targets.append("대금 수령 권한")

    actions: list[str] = []
    if authority_targets:
        owner_target = f"등기부에서 확인한 소유자 {owner_name}" if owner_name else "등기부상 소유자"
        actions.append(
            f"{owner_target}에게 대리인의 "
            f"{_with_particle(_join_korean(authority_targets), '을', '를')} 직접 확인하고 "
            "문자나 서면처럼 기록이 남는 방식으로 보관합니다."
        )
    if _slot_is_unresolved(document):
        actions.append(
            "확인한 권한이 구체적으로 적힌 위임 자료를 요청하고, "
            "소유자가 작성하거나 발급한 자료인지 대조합니다."
        )
    elif document_is_confirmed and scope_is_unresolved:
        actions.append(
            "현재 보유한 위임 자료에서 대리인이 체결할 수 있는 계약의 범위를 확인하고, "
            "소유자가 작성하거나 발급한 자료인지 대조합니다."
        )
    if _slot_is_unresolved(payment):
        account_target = account_value or "해당 계좌"
        actions.append(
            f"{account_target}로 계약금을 받을 권한이 있는지 소유자에게 별도로 확인하고, "
            "계좌 정보와 확인 기록을 함께 보관합니다."
        )
    elif account_is_non_owner and _slot_is_confirmed_true(payment):
        actions.append(
            f"{account_value}로 계약금을 받을 권한을 확인한 내용과 계좌 정보를 "
            "문자나 서면처럼 기록이 남는 형태로 보관합니다."
        )
    if not actions:
        actions.append(
            "위임 자료의 계약 체결·서명·대금 수령 범위와 계약금 계좌 정보를 최종 대조합니다."
        )

    reasons: list[str] = []
    if confirmed_text and unresolved_text:
        reasons.append(
            f"{_with_particle(confirmed_text, '은', '는')} 확인됐지만 "
            f"{_with_particle(unresolved_text, '은', '는')} 확인되지 않았습니다."
        )
    elif unresolved_text:
        reasons.append(
            f"{_with_particle(unresolved_text, '이', '가')} 확인되지 않았습니다."
        )
    if account_is_non_owner and _slot_is_unresolved(payment):
        reasons.append(
            "계약금 계좌가 소유자 본인 명의가 아니므로 계약 권한과 대금 수령 권한을 분리해 확인해야 합니다."
        )
    elif account_is_non_owner and _slot_is_confirmed_true(payment):
        reasons.append(
            "계약금 계좌가 소유자 본인 명의가 아니므로 확인한 대금 수령 권한과 계좌 정보를 기록으로 남겨야 합니다."
        )
    reasons.append(
        "실제 대리권이 없거나 확인된 범위를 넘어 계약한 경우에는 "
        "계약의 효력이 소유자에게 귀속되는지를 두고 분쟁이 생길 수 있습니다."
    )

    return {
        "core_judgment": " ".join(conclusion_parts),
        "immediate_actions": actions[:3],
        "reasons": _unique(reasons)[:4],
    }


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
    # assessment.core_judgment는 상태 엔진 내부 요약이다.
    # 근거와 실제 사용자 답변을 반영해 LLM이 만든 사용자용 핵심 결론을 유지한다.
    if failed_generation:
        answer["core_judgment"] = assessment.core_judgment
    elif (
        state.primary_issue_id == "q01_owner_proxy"
        and not follow_up_questions
    ):
        answer.update(_owner_proxy_final_payload(state))
    answer["hold_actions"] = assessment.hold_actions[:3]
    answer["follow_up_questions"] = [
        item.question
        for item in follow_up_questions[:1]
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
