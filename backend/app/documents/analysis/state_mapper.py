"""문서 분석·비교 결과를 q01~q20 ConversationState 슬롯에 반영한다."""

from __future__ import annotations

from typing import Any

from app.consultation.a_part.models import (
    ConversationState,
    FactSource,
    SlotStatus,
    add_issue_to_state,
    utc_now,
)
from app.consultation.a_part.state_policy import evaluate_conversation_risk
from app.documents.analysis.models import (
    AnalysisValueStatus,
    AnalyzedField,
    ComparisonStatus,
    DocumentComparisonResult,
    DocumentSlotUpdate,
    LeaseAnalysisResult,
    RegistryAnalysisResult,
    StateMappingRecord,
    StateMappingSummary,
)


def _evidence_text(field: AnalyzedField) -> str | None:
    if not field.evidences:
        return None
    evidence = field.evidences[0]
    return (
        f"문서 {evidence.document_id} {evidence.page_number}페이지 "
        f"({evidence.extraction_method}): {evidence.text}"
    )


def _field_update(
    *,
    issue_id: str,
    slot_key: str,
    field: AnalyzedField | None,
    document_id: str,
) -> DocumentSlotUpdate | None:
    if field is None or field.status == AnalysisValueStatus.UNKNOWN:
        return None
    return DocumentSlotUpdate(
        issue_id=issue_id,
        slot_key=slot_key,
        status=field.status,
        value=field.value,
        evidence_text=_evidence_text(field),
        confidence=field.confidence,
        document_ids=[document_id],
    )


def _not_applicable_update(
    *,
    issue_id: str,
    slot_key: str,
    document_id: str,
    evidence_text: str,
) -> DocumentSlotUpdate:
    return DocumentSlotUpdate(
        issue_id=issue_id,
        slot_key=slot_key,
        status=AnalysisValueStatus.CONFIRMED,
        value=None,
        evidence_text=evidence_text,
        confidence=1.0,
        document_ids=[document_id],
        not_applicable=True,
    )


def build_document_slot_updates(
    *,
    lease: LeaseAnalysisResult | None,
    registry: RegistryAnalysisResult | None,
    comparison: DocumentComparisonResult | None = None,
) -> list[DocumentSlotUpdate]:
    updates: list[DocumentSlotUpdate] = []

    def add(update: DocumentSlotUpdate | None) -> None:
        if update is not None:
            updates.append(update)

    if lease is not None:
        fields = lease.fields
        mappings = [
            ("q03_owner_lessor_mismatch", "contract_lessor_name", "lessor_name"),
            ("q07_mortgage", "deposit_amount", "deposit_amount"),
            ("q08_multiunit_priority", "deposit_amount", "deposit_amount"),
            ("q14_special_clause_deposit_return", "special_clause_text", "special_clause_text"),
            ("q15_after_contract_procedure", "move_in_date", "move_in_date"),
            ("q16_lease_report", "contract_address", "property_address"),
            ("q16_lease_report", "contract_date", "contract_date"),
            ("q16_lease_report", "deposit_amount", "deposit_amount"),
            ("q16_lease_report", "monthly_rent", "monthly_rent"),
            ("q18_address_mismatch", "contract_address", "property_address"),
            ("q19_deposit_transfer_mismatch", "contract_total_deposit", "deposit_amount"),
            ("q20_guarantee_check", "contract_start_date", "contract_start_date"),
            ("q20_guarantee_check", "contract_end_date", "contract_end_date"),
            ("q20_guarantee_check", "deposit_amount", "deposit_amount"),
            ("q20_guarantee_check", "housing_type", "housing_type"),
        ]
        for issue_id, slot_key, field_key in mappings:
            add(
                _field_update(
                    issue_id=issue_id,
                    slot_key=slot_key,
                    field=fields.get(field_key),
                    document_id=lease.document_id,
                )
            )

    if registry is not None:
        fields = registry.fields
        mappings = [
            ("q01_owner_proxy", "registered_owner_identified", "current_owners"),
            ("q02_co_owner", "co_owners_identified", "current_owners"),
            ("q02_co_owner", "ownership_shares_confirmed", "ownership_shares"),
            ("q03_owner_lessor_mismatch", "registry_owner_name", "current_owners"),
            ("q04_broker_account_payment", "registry_owner_identified", "current_owners"),
            ("q07_mortgage", "mortgage_exists", "mortgage_exists"),
            ("q07_mortgage", "maximum_secured_amount", "maximum_secured_amount"),
            ("q07_mortgage", "latest_registry_checked", "latest_registry_checked"),
            ("q09_registry_restriction_warning", "restriction_type", "restriction_types"),
            ("q09_registry_restriction_warning", "restriction_active", "active_restriction_exists"),
            ("q09_registry_restriction_warning", "latest_registry_checked", "latest_registry_checked"),
            ("q10_trust", "trust_registration_exists", "trust_registration_exists"),
            ("q10_trust", "trustee_identified", "trustees"),
            ("q17_household_certificate", "latest_registry_checked", "latest_registry_checked"),
            ("q18_address_mismatch", "registry_address", "registry_address"),
            ("q20_guarantee_check", "registry_checked", "latest_registry_checked"),
        ]
        for issue_id, slot_key, field_key in mappings:
            add(
                _field_update(
                    issue_id=issue_id,
                    slot_key=slot_key,
                    field=fields.get(field_key),
                    document_id=registry.document_id,
                )
            )

        restriction_field = fields.get("active_restriction_exists")
        if (
            restriction_field is not None
            and restriction_field.status == AnalysisValueStatus.CONFIRMED
            and restriction_field.value is False
            and not registry.restrictions
        ):
            for slot_key in (
                "restriction_type",
                "cancellation_status",
                "registration_date",
                "creditor_or_right_holder",
                "impact_explained",
            ):
                updates.append(
                    _not_applicable_update(
                        issue_id="q09_registry_restriction_warning",
                        slot_key=slot_key,
                        document_id=registry.document_id,
                        evidence_text=(
                            "등기부 분석에서 현재 유효한 압류·가압류 등 "
                            "권리 제한 항목을 확인하지 못했습니다."
                        ),
                    )
                )

        active_mortgages = [item for item in registry.mortgages if item.active is not False]
        prior_rights = [
            item.right_type
            for item in [*registry.restrictions, *registry.trusts]
            if item.active is not False
        ]
        if active_mortgages or prior_rights:
            updates.append(
                DocumentSlotUpdate(
                    issue_id="q07_mortgage",
                    slot_key="other_prior_rights",
                    status=AnalysisValueStatus.CONFIRMED,
                    value=prior_rights,
                    evidence_text="등기부 분석에서 현재 유효 가능성이 있는 권리관계를 확인했습니다.",
                    confidence=min(
                        [item.confidence for item in [*active_mortgages, *registry.restrictions, *registry.trusts]]
                        or [1.0]
                    ),
                    document_ids=[registry.document_id],
                )
            )

        if registry.restrictions:
            active = [item for item in registry.restrictions if item.active is not False]
            statuses = sorted({item.cancellation_status or "unknown" for item in registry.restrictions})
            dates = sorted({item.registration_date for item in registry.restrictions if item.registration_date})
            holders = sorted({item.holder for item in registry.restrictions if item.holder})
            updates.extend(
                [
                    DocumentSlotUpdate(
                        issue_id="q09_registry_restriction_warning",
                        slot_key="cancellation_status",
                        status=(
                            AnalysisValueStatus.CONFIRMED
                            if all(item.active is not None for item in registry.restrictions)
                            else AnalysisValueStatus.UNCERTAIN
                        ),
                        value=statuses,
                        evidence_text="등기부 권리 제한 항목의 말소 표시를 분석했습니다.",
                        confidence=min(item.confidence for item in registry.restrictions),
                        document_ids=[registry.document_id],
                    ),
                    DocumentSlotUpdate(
                        issue_id="q09_registry_restriction_warning",
                        slot_key="registration_date",
                        status=(AnalysisValueStatus.CONFIRMED if dates else AnalysisValueStatus.UNCERTAIN),
                        value=dates or None,
                        evidence_text="등기부 권리 제한 항목의 접수·설정일을 분석했습니다.",
                        confidence=min(item.confidence for item in registry.restrictions),
                        document_ids=[registry.document_id],
                    ),
                    DocumentSlotUpdate(
                        issue_id="q09_registry_restriction_warning",
                        slot_key="creditor_or_right_holder",
                        status=(AnalysisValueStatus.CONFIRMED if holders else AnalysisValueStatus.UNCERTAIN),
                        value=holders or None,
                        evidence_text="등기부 권리 제한 항목의 권리자를 분석했습니다.",
                        confidence=min(item.confidence for item in registry.restrictions),
                        document_ids=[registry.document_id],
                    ),
                ]
            )
            if active:
                updates.append(
                    DocumentSlotUpdate(
                        issue_id="q09_registry_restriction_warning",
                        slot_key="restriction_active",
                        status=AnalysisValueStatus.CONFIRMED,
                        value=True,
                        evidence_text="말소되지 않았거나 현재 유효 여부가 남아 있는 권리 제한이 있습니다.",
                        confidence=min(item.confidence for item in active),
                        document_ids=[registry.document_id],
                    )
                )

    if comparison is not None:
        for item in comparison.comparisons:
            if item.key == "owner_lessor" and item.status == ComparisonStatus.MISMATCH:
                updates.append(
                    DocumentSlotUpdate(
                        issue_id="q03_owner_lessor_mismatch",
                        slot_key="mismatch_reason_confirmed",
                        status=AnalysisValueStatus.CONFIRMED,
                        value=item.explanation,
                        evidence_text=item.explanation,
                        confidence=1.0,
                        document_ids=[value for value in [item.left_document_id, item.right_document_id] if value],
                    )
                )
            if item.key == "property_address":
                if item.status == ComparisonStatus.MATCH:
                    updates.append(
                        DocumentSlotUpdate(
                            issue_id="q18_address_mismatch",
                            slot_key="same_property_confirmed",
                            status=AnalysisValueStatus.CONFIRMED,
                            value=True,
                            evidence_text=item.explanation,
                            confidence=1.0,
                            document_ids=[value for value in [item.left_document_id, item.right_document_id] if value],
                        )
                    )
                elif item.status == ComparisonStatus.MISMATCH:
                    updates.extend(
                        [
                            DocumentSlotUpdate(
                                issue_id="q18_address_mismatch",
                                slot_key="mismatched_address_component",
                                status=AnalysisValueStatus.CONFIRMED,
                                value={"contract": item.left_value, "registry": item.right_value},
                                evidence_text=item.explanation,
                                confidence=1.0,
                                document_ids=[value for value in [item.left_document_id, item.right_document_id] if value],
                            ),
                            DocumentSlotUpdate(
                                issue_id="q18_address_mismatch",
                                slot_key="same_property_confirmed",
                                status=AnalysisValueStatus.CONFIRMED,
                                value=False,
                                evidence_text=item.explanation,
                                confidence=1.0,
                                document_ids=[value for value in [item.left_document_id, item.right_document_id] if value],
                            ),
                        ]
                    )
                elif item.status == ComparisonStatus.UNCERTAIN:
                    updates.append(
                        DocumentSlotUpdate(
                            issue_id="q18_address_mismatch",
                            slot_key="same_property_confirmed",
                            status=AnalysisValueStatus.UNCERTAIN,
                            value=None,
                            evidence_text=item.explanation,
                            confidence=0.5,
                            document_ids=[value for value in [item.left_document_id, item.right_document_id] if value],
                        )
                    )

    return updates


def _normalize_compare(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.strip().lower().split())
    if isinstance(value, list):
        return tuple(_normalize_compare(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), _normalize_compare(item)) for key, item in value.items()))
    return value


def _unique(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: list[Any] = []
    for value in values:
        comparable = _normalize_compare(value)
        if comparable in seen:
            continue
        seen.append(comparable)
        result.append(value)
    return result


def apply_document_analysis_to_state(
    state: ConversationState,
    *,
    updates: list[DocumentSlotUpdate],
    triggered_issue_ids: list[str],
    comparison_result_path: str | None,
    analysis_version: str,
) -> StateMappingSummary:
    summary = StateMappingSummary()

    for issue_id in triggered_issue_ids:
        if issue_id in state.all_issue_ids:
            continue
        add_issue_to_state(state, issue_id, as_related=True)
        summary.added_issue_ids.append(issue_id)

    for update in updates:
        issue_slots = state.issue_slots.get(update.issue_id)
        if issue_slots is None:
            summary.ignored.append(
                f"현재 활성 issue가 아니어서 반영하지 않음: {update.issue_id}.{update.slot_key}"
            )
            continue
        slot = issue_slots.get(update.slot_key)
        if slot is None:
            summary.ignored.append(
                f"정의되지 않은 슬롯이라 반영하지 않음: {update.issue_id}.{update.slot_key}"
            )
            continue
        if update.status == AnalysisValueStatus.UNKNOWN:
            continue

        previous_status = slot.status
        previous_value = slot.value
        conflict_created = False

        if update.not_applicable:
            slot.status = SlotStatus.NOT_APPLICABLE
            slot.value = None
            slot.conflicting_values = []
            slot.source = FactSource.DOCUMENT
            slot.evidence_text = update.evidence_text
            slot.updated_at = utc_now()
            summary.applied.append(
                StateMappingRecord(
                    issue_id=update.issue_id,
                    slot_key=update.slot_key,
                    previous_status=previous_status.value,
                    current_status=slot.status.value,
                    previous_value=previous_value,
                    current_value=None,
                    conflict_created=False,
                )
            )
            continue

        incoming_confirmed = update.status == AnalysisValueStatus.CONFIRMED and update.value is not None

        if incoming_confirmed:
            if previous_status == SlotStatus.CONFIRMED:
                if _normalize_compare(previous_value) == _normalize_compare(update.value):
                    continue
                slot.status = SlotStatus.CONFLICT
                slot.value = None
                slot.conflicting_values = _unique([previous_value, update.value])
                slot.source = FactSource.SYSTEM
                conflict_created = True
            elif previous_status == SlotStatus.CONFLICT:
                slot.conflicting_values = _unique([*slot.conflicting_values, update.value])
                slot.source = FactSource.SYSTEM
            else:
                slot.status = SlotStatus.CONFIRMED
                slot.value = update.value
                slot.conflicting_values = []
                slot.source = FactSource.DOCUMENT
        else:
            if (
                previous_status == SlotStatus.CONFIRMED
                and slot.source == FactSource.USER
            ):
                # 사용자가 원문을 직접 확인해 확정한 값은 이후의 모호한 OCR 결과로
                # 덮어쓰거나 conflict로 올리지 않는다.
                continue
            if previous_status == SlotStatus.CONFIRMED:
                slot.status = SlotStatus.CONFLICT
                slot.value = None
                slot.conflicting_values = _unique([previous_value, update.value or "uncertain_document_value"])
                slot.source = FactSource.SYSTEM
                conflict_created = True
            elif previous_status == SlotStatus.CONFLICT:
                if update.value is not None:
                    slot.conflicting_values = _unique([*slot.conflicting_values, update.value])
                slot.source = FactSource.SYSTEM
            else:
                slot.status = SlotStatus.UNCERTAIN
                slot.value = update.value
                slot.conflicting_values = []
                slot.source = FactSource.DOCUMENT

        slot.evidence_text = update.evidence_text
        slot.updated_at = utc_now()
        summary.applied.append(
            StateMappingRecord(
                issue_id=update.issue_id,
                slot_key=update.slot_key,
                previous_status=previous_status.value,
                current_status=slot.status.value,
                previous_value=previous_value,
                current_value=slot.value,
                conflict_created=conflict_created,
            )
        )

    state.document_analysis_version = analysis_version
    state.document_comparison_result_path = comparison_result_path
    assessment = evaluate_conversation_risk(state)
    state.last_risk_level = assessment.risk_level
    state.touch()
    summary.risk_level = assessment.risk_level
    return summary
