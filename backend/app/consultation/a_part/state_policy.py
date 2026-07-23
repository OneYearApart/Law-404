"""슬롯 상태를 위험 수준·보류 행동·추가 질문에 반영한다."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.consultation.a_part.issues import get_issue_definition
from app.consultation.a_part.models import (
    ConversationState,
    SlotState,
    SlotStatus,
)
from app.consultation.a_part.question_builder import FollowUpQuestion

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
    "q03_owner_lessor_mismatch": (
        "계약서 서명 또는 계약 진행",
        "계약금 또는 잔금 송금",
    ),
    "q04_broker_account_payment": ("계약금 송금",),
    "q05_account_change_before_contract": ("계약금 또는 잔금 송금",),
    "q06_broker_explanation_mismatch": ("정정 전 계약서 서명 또는 계약 진행",),
    "q07_mortgage": ("확인 전 계약서 서명 또는 계약 진행", "계약금 또는 잔금 송금"),
    "q08_multiunit_priority": (
        "확인 전 계약서 서명 또는 계약 진행",
        "계약금 또는 잔금 송금",
    ),
    "q09_registry_restriction_warning": (
        "계약서 서명 또는 계약 진행",
        "계약금 또는 잔금 송금",
    ),
    "q10_trust": ("계약서 서명 또는 계약 진행", "계약금 또는 잔금 송금"),
    "q14_special_clause_deposit_return": (
        "특약 정정 전 계약서 서명 또는 계약 진행",
        "계약금 송금",
    ),
    "q18_address_mismatch": ("주소 확인·정정 전 계약서 서명", "계약금 또는 잔금 송금"),
    "q19_deposit_transfer_mismatch": ("차액 확인 전 추가 송금 또는 잔금 지급",),
}

Q01_CIVIL_ACT_REFERENCES: dict[str, dict[str, Any]] = {
    "114": {
        "evidence_id": 114,
        "collection": "legal_sources",
        "document_id": "law_001706_제114조_2",
        "source_id": "001706",
        "source_type": "law",
        "title": "민법 제114조",
        "issue_id": "q01_owner_proxy",
        "similarity": 1.0,
        "rerank_score": 1.0,
        "text_preview": (
            "민법 제114조(대리행위의 효력) ① 대리인이 그 권한 내에서 본인을 위한 것임을 "
            "표시한 의사표시는 직접 본인에게 대하여 효력이 생긴다. ② 제1항의 규정은 "
            "대리인에 대한 제3자의 의사표시에 준용한다."
        ),
    },
    "130": {
        "evidence_id": 130,
        "collection": "legal_sources",
        "document_id": "law_001706_제130조",
        "source_id": "001706",
        "source_type": "law",
        "title": "민법 제130조",
        "issue_id": "q01_owner_proxy",
        "similarity": 1.0,
        "rerank_score": 1.0,
        "text_preview": (
            "민법 제130조(무권대리) 대리권 없는 자가 타인의 대리인으로 한 계약은 "
            "본인이 이를 추인하지 아니하면 본인에 대하여 효력이 없다."
        ),
    },
    "135": {
        "evidence_id": 135,
        "collection": "legal_sources",
        "document_id": "law_001706_제135조",
        "source_id": "001706",
        "source_type": "law",
        "title": "민법 제135조",
        "issue_id": "q01_owner_proxy",
        "similarity": 1.0,
        "rerank_score": 1.0,
        "text_preview": (
            "민법 제135조(상대방에 대한 무권대리인의 책임) 다른 자의 대리인으로서 계약을 "
            "맺은 자가 그 대리권을 증명하지 못하고 본인의 추인도 받지 못한 경우에는 "
            "상대방의 선택에 따라 계약을 이행하거나 손해를 배상할 책임이 있다."
        ),
    },
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
    return slot.key in TRUE_REQUIRED_KEYS or slot.key.endswith(TRUE_REQUIRED_SUFFIXES)


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
    return bool(slot and slot.status == SlotStatus.CONFIRMED and slot.value is True)


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


def _slot_has_conflict(slot: SlotState | None) -> bool:
    return bool(slot and slot.status == SlotStatus.CONFLICT)


def _text_slot_is_confirmed(slot: SlotState | None) -> bool:
    return bool(slot and slot.status == SlotStatus.CONFIRMED and _slot_text(slot))


def _owner_proxy_slots(state: ConversationState) -> dict[str, SlotState | None]:
    issue_id = "q01_owner_proxy"
    return {
        "owner": _slot_for(state, issue_id, "registered_owner_identified"),
        "intent": _slot_for(state, issue_id, "owner_proxy_intent_confirmed"),
        "document": _slot_for(state, issue_id, "delegation_document_available"),
        "scope": _slot_for(state, issue_id, "delegation_scope_confirmed"),
        "signature": _slot_for(state, issue_id, "signature_authority_confirmed"),
        "payment": _slot_for(state, issue_id, "payment_authority_confirmed"),
        "account": _slot_for(state, issue_id, "payment_account_holder"),
    }


def _owner_proxy_account_state(account: SlotState | None) -> tuple[str, str]:
    """계좌 상태를 owner/non_owner/unknown 세 종류로 고정한다."""

    if not _text_slot_is_confirmed(account):
        return "unknown", ""

    value = _account_text(account)
    owner_markers = (
        "소유자 본인",
        "소유자 명의",
        "임대인 본인",
        "임대인 명의",
    )
    if any(marker in value for marker in owner_markers):
        return "owner", value
    return "non_owner", value


def owner_proxy_progress_display(
    state: ConversationState,
    slot: SlotState,
    *,
    default_display_value: str,
) -> tuple[str, str]:
    """q01 진행 화면에서 소유자 미확인 상태의 조건부 사실을 표시한다."""

    if state.primary_issue_id != "q01_owner_proxy":
        return slot.label, default_display_value

    slots = _owner_proxy_slots(state)
    owner_identified = _text_slot_is_confirmed(slots["owner"])
    if owner_identified:
        return slot.label, default_display_value

    dependent_labels = {
        "owner_proxy_intent_confirmed": "대리 의사 확인",
        "delegation_document_available": "위임 자료 보유",
        "delegation_scope_confirmed": "계약 체결 범위",
        "signature_authority_confirmed": "서명 권한",
        "payment_authority_confirmed": "대금 수령 권한",
    }
    if slot.key in dependent_labels and _slot_is_confirmed_true(slot):
        return (
            dependent_labels[slot.key],
            "사용자 답변상 확인함 · 실제 소유자 대조 필요",
        )

    if slot.key == "payment_account_holder" and _text_slot_is_confirmed(slot):
        account_state, _ = _owner_proxy_account_state(slot)
        if account_state == "owner":
            return (
                slot.label,
                "소유자 본인 명의라고 안내받음 · 등기부 대조 필요",
            )

    return slot.label, default_display_value


def _owner_proxy_final_payload(state: ConversationState) -> dict[str, Any]:
    """q01의 위험 수준과 최종 문장을 모든 슬롯 조합에 따라 결정한다.

    q01에서는 LLM이 만든 결론·행동·이유를 사용하지 않는다. RAG가 가져온
    참고 근거만 유지하고, 사용자 답변 상태는 아래 규칙으로만 해석한다.
    """

    slots = _owner_proxy_slots(state)
    owner = slots["owner"]
    intent = slots["intent"]
    document = slots["document"]
    scope = slots["scope"]
    signature = slots["signature"]
    payment = slots["payment"]
    account = slots["account"]

    slot_pairs = [
        (owner, "등기부상 실제 소유자"),
        (intent, "소유자의 대리 의사"),
        (document, "위임 자료 보유 여부"),
        (scope, "계약 체결 범위"),
        (signature, "대리인의 서명 권한"),
        (payment, "대금 수령 권한"),
        (account, "계약금 계좌 예금주"),
    ]
    conflict_labels = [label for slot, label in slot_pairs if _slot_has_conflict(slot)]
    if conflict_labels:
        conflict_text = _join_korean(conflict_labels)
        return {
            "risk_level": "진행 보류 권장",
            "core_judgment": (
                f"앞서 답한 {_with_particle(conflict_text, '이', '가')} 서로 다릅니다. "
                "실제 등기부·위임 자료·계좌 정보를 다시 확인해 충돌을 해결하기 전에는 "
                "계약서 서명과 계약금 송금을 보류하세요."
            ),
            "immediate_actions": [
                f"{_with_particle(conflict_text, '을', '를')} 실제 문서와 확인 기록으로 다시 대조합니다.",
                "서로 다른 답변 중 어느 내용이 맞는지 확인한 뒤 해당 질문에 다시 답합니다.",
            ],
            "hold_actions": ["계약서 서명 또는 계약 진행", "계약금 또는 잔금 송금"],
            "reasons": [
                "같은 확인 항목에 서로 다른 답변이 저장돼 현재 사실관계를 확정할 수 없습니다.",
                "대리권의 존재와 범위가 불명확한 상태에서는 계약 효력의 귀속을 두고 분쟁이 생길 수 있습니다.",
            ],
            "required_information": conflict_labels,
            "confirmation_message": None,
        }

    owner_identified = _text_slot_is_confirmed(owner)
    owner_name = _slot_text(owner)
    intent_yes = _slot_is_confirmed_true(intent)
    document_yes = _slot_is_confirmed_true(document)
    scope_yes = _slot_is_confirmed_true(scope)
    signature_yes = _slot_is_confirmed_true(signature)
    payment_yes = _slot_is_confirmed_true(payment)
    account_state, account_value = _owner_proxy_account_state(account)

    confirmed_authority_labels: list[str] = []
    if intent_yes:
        confirmed_authority_labels.append("대리 의사")
    if document_yes:
        confirmed_authority_labels.append("위임 자료")
    if scope_yes:
        confirmed_authority_labels.append("계약 체결 범위")
    if signature_yes:
        confirmed_authority_labels.append("서명 권한")
    if payment_yes:
        confirmed_authority_labels.append("대금 수령 권한")

    unresolved_authority_labels: list[str] = []
    if not intent_yes:
        unresolved_authority_labels.append("소유자의 대리 의사")
    if not document_yes:
        unresolved_authority_labels.append("권한을 입증할 위임 자료")
    if not scope_yes:
        unresolved_authority_labels.append("구체적인 계약 체결 범위")
    if not signature_yes:
        unresolved_authority_labels.append("대리인의 서명 권한")
    if not payment_yes:
        unresolved_authority_labels.append("대금 수령 권한")

    # 실제 소유자 확인은 모든 대리 의사·권한 판단의 선행 조건이다.
    if not owner_identified:
        conclusion_parts = [
            "등기부상 실제 소유자를 확인하지 못해, 현재 확인한 대리 의사와 권한이 "
            "실제 소유자에게서 나온 것인지 확정하기 어렵습니다."
        ]
        tentative_text = _join_korean(confirmed_authority_labels)
        if tentative_text:
            if document_yes:
                conclusion_parts.append(
                    f"사용자 답변상 {_with_particle(tentative_text, '은', '는')} 확인됐지만, "
                    "실제 소유자와 위임 자료의 작성·확인 주체가 일치하는지 먼저 대조해야 합니다."
                )
            else:
                conclusion_parts.append(
                    f"사용자 답변상 {_with_particle(tentative_text, '은', '는')} 확인됐지만, "
                    "이를 뒷받침할 위임 자료는 확인하지 못했습니다. 먼저 실제 소유자를 확인한 뒤 "
                    "그 소유자가 작성하거나 발급한 위임 자료를 요청해야 합니다."
                )

        if account_state == "owner":
            conclusion_parts.append(
                "계약금 계좌는 소유자 본인 명의라고 안내받았지만, "
                "실제 소유자를 확인하기 전에는 그 일치 여부를 확정할 수 없습니다."
            )
        elif account_state == "non_owner":
            conclusion_parts.append(
                f"계약금 계좌도 소유자 본인 명의가 아닌 {account_value}로 확인됐습니다."
            )
        else:
            conclusion_parts.append("계약금 계좌의 예금주도 확인하지 못했습니다.")

        conclusion_parts.append(
            "소유자 신원, 위임 자료, 권한 범위와 계좌 정보를 서로 대조하기 전에는 "
            "계약서 서명과 계약금 송금을 보류하세요."
        )

        actions = [
            "최신 등기부등본에서 실제 소유자의 이름을 확인합니다.",
        ]
        if document_yes:
            actions.append(
                "대리 의사를 확인한 사람과 현재 보유한 위임 자료의 작성자가 등기부상 소유자와 "
                "일치하는지 신분 정보와 함께 대조합니다."
            )
        else:
            actions.append(
                "대리 의사를 확인한 사람이 등기부상 소유자와 동일한 사람인지 신분 정보와 함께 대조합니다."
            )
            actions.append(
                "실제 소유자가 작성하거나 발급한 위임 자료를 요청하고, 계약 체결·서명·대금 수령 "
                "범위와 계좌 정보가 구체적으로 적혀 있는지 확인합니다."
            )

        if len(actions) < 3:
            if account_state == "unknown":
                actions.append(
                    "계약금 계좌의 예금주를 확인하고 실제 소유자와의 관계를 대조합니다."
                )
            elif account_state == "non_owner" and payment_yes:
                actions.append(
                    f"{account_value}로 계약금을 받을 권한을 확인한 기록과 계좌 정보를 함께 보관합니다."
                )
            else:
                actions.append(
                    "실제 소유자를 확인한 뒤 계약 체결·서명·대금 수령 권한과 계좌 정보를 다시 대조합니다."
                )

        required_information = ["등기부상 실제 소유자"]
        required_information.extend(unresolved_authority_labels)
        if account_state == "unknown":
            required_information.append("계약금 계좌 예금주")

        reasons = [
            "실제 소유자를 확인하지 못해 대리 의사와 권한의 출처를 확정할 수 없습니다.",
            "가족관계만으로 계약 체결·서명·대금 수령 권한이 확인되는 것은 아닙니다.",
            "실제 대리권이 없거나 확인된 범위를 넘어 계약한 경우에는 계약의 효력이 "
            "소유자에게 귀속되는지를 두고 분쟁이 생길 수 있습니다.",
        ]
        if account_state == "non_owner":
            reasons.insert(
                2,
                "계약금 계좌가 소유자 본인 명의가 아니므로 실제 소유자와 수령 권한을 함께 대조해야 합니다.",
            )

        return {
            "risk_level": "진행 보류 권장",
            "core_judgment": " ".join(conclusion_parts),
            "immediate_actions": _unique(actions)[:3],
            "hold_actions": ["계약서 서명 또는 계약 진행", "계약금 또는 잔금 송금"],
            "reasons": _unique(reasons)[:4],
            "required_information": _unique(required_information)[:6],
            "confirmation_message": None,
        }

    contract_blocked = not all((intent_yes, document_yes, scope_yes, signature_yes))
    payment_blocked = not payment_yes or account_state == "unknown"

    if contract_blocked or payment_blocked:
        risk_level = "진행 보류 권장"
    elif account_state == "non_owner":
        risk_level = "주의 필요"
    else:
        risk_level = "확인 필요"

    hold_actions: list[str] = []
    if contract_blocked:
        hold_actions.extend(("계약서 서명 또는 계약 진행", "계약금 또는 잔금 송금"))
    elif payment_blocked or account_state == "non_owner":
        hold_actions.append("계약금 또는 잔금 송금")

    confirmed_text = _join_korean(confirmed_authority_labels)
    unresolved_text = _join_korean(unresolved_authority_labels)
    conclusion_parts: list[str] = []

    if unresolved_text and confirmed_text:
        owner_subject = _with_particle(f"등기부상 소유자 {owner_name}", "과", "와")
        conclusion_parts.append(
            f"{owner_subject} 사용자 답변상 "
            f"{_with_particle(confirmed_text, '은', '는')} 확인했지만, "
            f"{_with_particle(unresolved_text, '은', '는')} 확인하지 못했습니다."
        )
    elif unresolved_text:
        owner_subject = _with_particle(f"등기부상 소유자 {owner_name}", "은", "는")
        conclusion_parts.append(
            f"{owner_subject} 확인했지만, "
            f"{_with_particle(unresolved_text, '은', '는')} 확인하지 못했습니다."
        )
    else:
        conclusion_parts.append(
            f"사용자가 입력한 답변 기준으로 등기부상 소유자 {owner_name}, "
            "소유자의 대리 의사, 위임 자료, 계약 체결 범위, "
            "대리인의 서명 권한과 대금 수령 권한을 모두 확인했습니다."
        )

    if account_state == "owner":
        conclusion_parts.append("계약금 계좌도 소유자 본인 명의로 확인됐습니다.")
    elif account_state == "non_owner":
        conclusion_parts.append(
            f"계약금 계좌는 소유자 본인 명의가 아닌 {account_value}로 확인됐습니다."
        )
    else:
        conclusion_parts.append("계약금 계좌 예금주는 확인하지 못했습니다.")

    if contract_blocked:
        conclusion_parts.append(
            f"{_with_particle(unresolved_text, '을', '를')} 확인하기 전에는 "
            "계약서 서명과 계약금 송금을 보류하세요."
        )
    elif payment_blocked:
        conclusion_parts.append(
            "계좌 예금주와 대금 수령 권한을 확인하기 전에는 계약금 송금을 보류하세요."
        )
    elif account_state == "non_owner":
        conclusion_parts.append(
            "확인한 대금 수령 권한과 계좌 정보가 위임 자료 및 소유자의 확인 기록과 "
            "일치하는지 최종 대조하기 전에는 계약금 송금을 보류하세요."
        )
    else:
        conclusion_parts.append(
            "실제 계약서 내용과 위임 자료의 권한 범위가 일치하는지 최종 대조한 뒤 진행하세요."
        )

    actions: list[str] = []
    if not intent_yes:
        actions.append(
            f"등기부에서 확인한 소유자 {owner_name}에게 가족이 대신 계약하는 것을 승인했는지 "
            "직접 확인하고 기록을 남깁니다."
        )

    missing_document_authorities: list[str] = []
    if not scope_yes:
        missing_document_authorities.append("계약 체결 범위")
    if not signature_yes:
        missing_document_authorities.append("서명 권한")
    if not payment_yes:
        missing_document_authorities.append("대금 수령 권한")

    if not document_yes:
        target_text = _join_korean(missing_document_authorities)
        if not target_text:
            target_text = "계약 체결·서명·대금 수령 권한"
        actions.append(
            f"{_with_particle(target_text, '이', '가')} 구체적으로 적힌 위임 자료를 요청하고, "
            "소유자가 작성하거나 발급한 자료인지 대조합니다."
        )
    elif missing_document_authorities:
        target_text = _join_korean(missing_document_authorities)
        actions.append(
            f"현재 보유한 위임 자료에서 {_with_particle(target_text, '을', '를')} 확인하고, "
            "소유자가 작성하거나 발급한 자료인지 대조합니다."
        )

    if not payment_yes:
        account_target = account_value or "해당 계좌"
        actions.append(
            f"{account_target}로 계약금을 받을 권한이 있는지 소유자에게 별도로 확인하고, "
            "계좌 정보와 확인 기록을 함께 보관합니다."
        )
    elif account_state == "unknown":
        actions.append(
            "계약금 계좌의 예금주를 확인하고, 확인한 대금 수령 권한의 대상 계좌와 일치하는지 대조합니다."
        )
    elif account_state == "non_owner":
        actions.append(
            f"{account_value}로 계약금을 받을 권한을 확인한 내용과 계좌 정보를 "
            "문자나 서면처럼 기록이 남는 형태로 보관합니다."
        )

    if not actions:
        actions.extend(
            [
                "위임 자료의 계약 체결·서명·대금 수령 범위가 실제 계약서 내용과 일치하는지 최종 대조합니다.",
                "소유자와 확인한 권한 내용, 위임 자료와 계좌 정보를 계약서와 함께 보관합니다.",
            ]
        )

    reasons: list[str] = []
    if unresolved_text:
        if confirmed_text:
            reasons.append(
                f"{_with_particle(confirmed_text, '은', '는')} 확인됐지만 "
                f"{_with_particle(unresolved_text, '은', '는')} 확인되지 않았습니다."
            )
        else:
            reasons.append(
                f"{_with_particle(unresolved_text, '이', '가')} 확인되지 않았습니다."
            )
    else:
        reasons.append(
            "대리 계약 판단에 필요한 핵심 권한과 위임 자료는 사용자 답변상 모두 확인됐습니다."
        )

    if account_state == "non_owner":
        if payment_yes:
            reasons.append(
                "계약금 계좌가 소유자 본인 명의가 아니므로 확인한 수령 권한과 계좌 정보를 기록으로 남겨야 합니다."
            )
        else:
            reasons.append(
                "계약금 계좌가 소유자 본인 명의가 아니므로 대금 수령 권한을 별도로 확인해야 합니다."
            )
    elif account_state == "unknown":
        reasons.append(
            "계약금 계좌 예금주를 확인하지 못해 송금 대상을 확정할 수 없습니다."
        )

    if contract_blocked or payment_blocked or account_state == "non_owner":
        reasons.append(
            "실제 대리권이 없거나 확인된 범위를 넘어 계약한 경우에는 계약의 효력이 "
            "소유자에게 귀속되는지를 두고 분쟁이 생길 수 있습니다."
        )
    else:
        reasons.append(
            "입력한 답변이 실제 등기부·위임 자료·계약서와 일치하는지는 계약 전에 최종 대조해야 합니다."
        )

    required_information = list(unresolved_authority_labels)
    if account_state == "unknown":
        required_information.append("계약금 계좌 예금주")

    return {
        "risk_level": risk_level,
        "core_judgment": " ".join(conclusion_parts),
        "immediate_actions": _unique(actions)[:3],
        "hold_actions": _unique(hold_actions)[:3],
        "reasons": _unique(reasons)[:4],
        "required_information": _unique(required_information)[:6],
        "confirmation_message": None,
    }


def _reference_title(reference: Any) -> str:
    if isinstance(reference, dict):
        return str(reference.get("title") or "").strip()
    return str(getattr(reference, "title", "") or "").strip()


def _q01_authority_is_confirmed(state: ConversationState) -> bool:
    slots = _owner_proxy_slots(state)
    account_state, _ = _owner_proxy_account_state(slots["account"])
    return bool(
        _text_slot_is_confirmed(slots["owner"])
        and _slot_is_confirmed_true(slots["intent"])
        and _slot_is_confirmed_true(slots["document"])
        and _slot_is_confirmed_true(slots["scope"])
        and _slot_is_confirmed_true(slots["signature"])
        and _slot_is_confirmed_true(slots["payment"])
        and account_state != "unknown"
        and not any(_slot_has_conflict(slot) for slot in slots.values())
    )


def _q01_reference_payload(
    state: ConversationState,
    current_references: list[Any],
) -> list[dict[str, Any]]:
    """q01의 근거를 정상 권한 조합과 미확인 조합으로 분리한다."""

    article_keys = ["114"] if _q01_authority_is_confirmed(state) else ["130", "135"]
    references = [dict(Q01_CIVIL_ACT_REFERENCES[key]) for key in article_keys]

    for reference in current_references:
        title = _reference_title(reference)
        if "주택임대차보호법 해설집" not in title:
            continue
        item = (
            dict(reference)
            if isinstance(reference, dict)
            else reference.model_dump(mode="python")
        )
        references.append(item)
        break

    for index, reference in enumerate(references, start=1):
        reference["evidence_id"] = index

    return references[:3]


def _owner_proxy_risk_assessment(
    state: ConversationState,
) -> ConversationRiskAssessment:
    payload = _owner_proxy_final_payload(state)
    slots = _owner_proxy_slots(state)
    conflict_labels = [
        slot.label
        for slot in slots.values()
        if slot is not None and slot.status == SlotStatus.CONFLICT
    ]
    return ConversationRiskAssessment(
        risk_level=str(payload["risk_level"]),
        core_judgment=str(payload["core_judgment"]),
        hold_actions=list(payload["hold_actions"]),
        unresolved_critical_labels=list(payload["required_information"]),
        conflict_labels=_unique(conflict_labels),
    )


def _hold_actions_for_state(state: ConversationState) -> list[str]:
    actions: list[str] = []
    for issue_id in state.all_issue_ids:
        actions.extend(ISSUE_HOLD_ACTIONS.get(issue_id, ()))
    return _unique(actions)[:3]


def evaluate_conversation_risk(
    state: ConversationState,
) -> ConversationRiskAssessment:
    if state.primary_issue_id == "q01_owner_proxy":
        return _owner_proxy_risk_assessment(state)

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
        issue_id in HIGH_RISK_ISSUES for issue_id in state.all_issue_ids
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
                _hold_actions_for_state(state) if has_high_risk_issue else []
            ),
            unresolved_critical_labels=unresolved_labels,
            conflict_labels=conflict_labels,
        )

    if unresolved_labels:
        labels = ", ".join(unresolved_labels[:3])
        return ConversationRiskAssessment(
            risk_level=("진행 보류 권장" if has_high_risk_issue else "확인 필요"),
            core_judgment=(
                f"현재 답변에서 일부 사실은 확인됐지만 핵심 확인 항목이 남아 있습니다: {labels}. "
                "남은 항목을 확인한 뒤 위험 수준과 다음 행동을 다시 판단해야 합니다."
            ),
            hold_actions=(
                _hold_actions_for_state(state) if has_high_risk_issue else []
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
    """기존 RAG 근거는 유지하고 상태 규칙으로 사용자 답변 부분을 갱신한다."""

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

    q01_is_final = (
        state.primary_issue_id == "q01_owner_proxy" and not follow_up_questions
    )
    q01_payload: dict[str, Any] | None = None

    # q01 최종 답변은 LLM 성공 여부와 관계없이 규칙 결과를 사용한다.
    # 참고 근거도 권한 확인 상태에 맞춰 민법 조문과 검색된 해설집으로 고정한다.
    if q01_is_final:
        q01_payload = _owner_proxy_final_payload(state)
        answer.update(q01_payload)
        q01_references = _q01_reference_payload(
            state,
            list(answer.get("references") or []),
        )
        answer["references"] = q01_references
        data["selected_evidence"] = q01_references
    elif failed_generation:
        answer["core_judgment"] = assessment.core_judgment

    answer["risk_level"] = assessment.risk_level
    answer["hold_actions"] = assessment.hold_actions[:3]
    answer["follow_up_questions"] = [item.question for item in follow_up_questions[:1]]

    if q01_payload is not None:
        # 내부 issue 이름이 섞인 generic unresolved label을 최종 화면에 넣지 않는다.
        answer["required_information"] = list(
            q01_payload.get("required_information") or []
        )[:6]
    else:
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
