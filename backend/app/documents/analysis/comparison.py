"""계약서와 등기부 분석 결과를 정규화된 값으로 비교한다."""

from __future__ import annotations

from app.documents.analysis.models import (
    AnalysisValueStatus,
    ComparisonItem,
    ComparisonStatus,
    DocumentComparisonResult,
    LeaseAnalysisResult,
    RegistryAnalysisResult,
)
from app.documents.analysis.normalization import (
    compare_addresses_safely,
    normalize_name,
)


def _field(result, key: str):
    return result.fields.get(key)


def _unavailable_status(left, right) -> ComparisonStatus | None:
    if left is None or right is None:
        return ComparisonStatus.MISSING
    if (
        left.status == AnalysisValueStatus.UNKNOWN
        or right.status == AnalysisValueStatus.UNKNOWN
    ):
        return ComparisonStatus.MISSING
    if left.status in {
        AnalysisValueStatus.UNCERTAIN,
        AnalysisValueStatus.CONFLICT,
    } or right.status in {
        AnalysisValueStatus.UNCERTAIN,
        AnalysisValueStatus.CONFLICT,
    }:
        return ComparisonStatus.UNCERTAIN
    return None


def compare_owner_and_lessor(
    lease: LeaseAnalysisResult,
    registry: RegistryAnalysisResult,
) -> ComparisonItem:
    lessor = _field(lease, "lessor_name")
    owners = _field(registry, "current_owners")
    if lessor is None or owners is None:
        return ComparisonItem(
            key="owner_lessor",
            label="계약서 임대인과 등기부 소유자",
            status=ComparisonStatus.MISSING,
            left_document_id=lease.document_id,
            right_document_id=registry.document_id,
            left_value=(lessor.value if lessor else None),
            right_value=(owners.value if owners else None),
            explanation="비교할 임대인 또는 소유자 값이 없습니다.",
        )
    if (
        lessor.status == AnalysisValueStatus.UNKNOWN
        or owners.status == AnalysisValueStatus.UNKNOWN
        or lessor.value in {None, ""}
        or owners.value is None
        or owners.value == ""
        or owners.value == []
    ):
        return ComparisonItem(
            key="owner_lessor",
            label="계약서 임대인과 등기부 소유자",
            status=ComparisonStatus.MISSING,
            left_document_id=lease.document_id,
            right_document_id=registry.document_id,
            left_value=lessor.value,
            right_value=owners.value,
            explanation="비교할 임대인 또는 소유자 값이 없습니다.",
        )
    if (
        lessor.status == AnalysisValueStatus.CONFLICT
        or owners.status == AnalysisValueStatus.CONFLICT
    ):
        return ComparisonItem(
            key="owner_lessor",
            label="계약서 임대인과 등기부 소유자",
            status=ComparisonStatus.UNCERTAIN,
            left_document_id=lease.document_id,
            right_document_id=registry.document_id,
            left_value=lessor.value,
            right_value=owners.value,
            explanation="문서 안에서 이름 후보가 충돌해 일치 여부를 확정하지 않습니다.",
        )

    normalized_lessor = normalize_name(str(lessor.value))
    owner_values = owners.value if isinstance(owners.value, list) else [owners.value]
    normalized_owners = [normalize_name(str(value)) for value in owner_values]
    matched = normalized_lessor in normalized_owners
    source_uncertain = (
        lessor.status == AnalysisValueStatus.UNCERTAIN
        or owners.status == AnalysisValueStatus.UNCERTAIN
    )
    warnings: list[str] = []
    if source_uncertain:
        warnings.append(
            "한쪽 이름이 OCR 신뢰도 때문에 uncertain이지만 정규화된 이름을 별도로 비교했습니다."
        )
    if matched:
        status = ComparisonStatus.MATCH
        explanation = "계약서 임대인이 등기부 현재 소유자 목록에 포함됩니다."
    elif source_uncertain:
        status = ComparisonStatus.UNCERTAIN
        explanation = "OCR 신뢰도가 낮은 이름에서 차이가 보여 불일치를 확정하지 않고 재확인 대상으로 남깁니다."
    else:
        status = ComparisonStatus.MISMATCH
        explanation = "계약서 임대인이 등기부 현재 소유자 목록과 일치하지 않습니다."
    return ComparisonItem(
        key="owner_lessor",
        label="계약서 임대인과 등기부 소유자",
        status=status,
        left_document_id=lease.document_id,
        right_document_id=registry.document_id,
        left_value=lessor.value,
        right_value=owners.value,
        normalized_left=normalized_lessor,
        normalized_right=normalized_owners,
        explanation=explanation,
        warnings=warnings,
    )


def compare_addresses(
    lease: LeaseAnalysisResult,
    registry: RegistryAnalysisResult,
) -> ComparisonItem:
    contract_address = _field(lease, "property_address")
    registry_address = _field(registry, "registry_address")
    if contract_address is None or registry_address is None:
        return ComparisonItem(
            key="property_address",
            label="계약서 주소와 등기부 주소",
            status=ComparisonStatus.MISSING,
            left_document_id=lease.document_id,
            right_document_id=registry.document_id,
            left_value=(contract_address.value if contract_address else None),
            right_value=(registry_address.value if registry_address else None),
            explanation="비교할 주소가 없어 동일 목적물 여부를 확인하지 못했습니다.",
        )
    if (
        contract_address.status == AnalysisValueStatus.UNKNOWN
        or registry_address.status == AnalysisValueStatus.UNKNOWN
        or contract_address.value in {None, ""}
        or registry_address.value in {None, ""}
    ):
        return ComparisonItem(
            key="property_address",
            label="계약서 주소와 등기부 주소",
            status=ComparisonStatus.MISSING,
            left_document_id=lease.document_id,
            right_document_id=registry.document_id,
            left_value=contract_address.value,
            right_value=registry_address.value,
            explanation="비교할 주소가 없어 동일 목적물 여부를 확인하지 못했습니다.",
        )
    if (
        contract_address.status == AnalysisValueStatus.CONFLICT
        or registry_address.status == AnalysisValueStatus.CONFLICT
    ):
        return ComparisonItem(
            key="property_address",
            label="계약서 주소와 등기부 주소",
            status=ComparisonStatus.UNCERTAIN,
            left_document_id=lease.document_id,
            right_document_id=registry.document_id,
            left_value=contract_address.value,
            right_value=registry_address.value,
            explanation="문서 안에서 주소 후보가 충돌해 동일 목적물 여부를 확정하지 않습니다.",
        )

    matched, details = compare_addresses_safely(
        str(contract_address.value),
        str(registry_address.value),
    )
    source_uncertain = (
        contract_address.status == AnalysisValueStatus.UNCERTAIN
        or registry_address.status == AnalysisValueStatus.UNCERTAIN
    )
    warnings: list[str] = []
    if source_uncertain:
        warnings.append(
            "한쪽 주소가 OCR 신뢰도 때문에 uncertain이지만 핵심 주소 구성요소를 별도로 비교했습니다."
        )

    if matched is True:
        status = ComparisonStatus.MATCH
        explanation = (
            "주소 전체 문자열 또는 구·동·건물명·층·호수의 핵심 구성요소가 일치합니다."
        )
    elif matched is False:
        status = (
            ComparisonStatus.UNCERTAIN
            if source_uncertain
            else ComparisonStatus.MISMATCH
        )
        explanation = (
            "OCR 신뢰도가 낮은 주소에서 구성요소 차이가 보여 불일치를 확정하지 않고 재확인 대상으로 남깁니다."
            if source_uncertain
            else "주소 핵심 구성요소에서 서로 다른 값이 확인됐습니다."
        )
    else:
        status = ComparisonStatus.UNCERTAIN
        explanation = "OCR 주소에서 비교 가능한 핵심 구성요소가 부족해 동일 목적물 여부를 확정하지 않습니다."
    return ComparisonItem(
        key="property_address",
        label="계약서 주소와 등기부 주소",
        status=status,
        left_document_id=lease.document_id,
        right_document_id=registry.document_id,
        left_value=contract_address.value,
        right_value=registry_address.value,
        normalized_left=details.get("normalized_left"),
        normalized_right=details.get("normalized_right"),
        explanation=explanation,
        warnings=warnings,
    )


def compare_mortgage_clause(
    lease: LeaseAnalysisResult,
    registry: RegistryAnalysisResult,
) -> ComparisonItem:
    active_mortgages = [item for item in registry.mortgages if item.active is not False]
    if not registry.mortgages:
        return ComparisonItem(
            key="mortgage_cancellation_clause",
            label="근저당과 말소 특약",
            status=ComparisonStatus.NOT_APPLICABLE,
            left_document_id=lease.document_id,
            right_document_id=registry.document_id,
            explanation="등기부 분석에서 근저당을 확인하지 못해 말소 특약 비교를 적용하지 않습니다.",
        )
    if not active_mortgages:
        return ComparisonItem(
            key="mortgage_cancellation_clause",
            label="근저당과 말소 특약",
            status=ComparisonStatus.NOT_APPLICABLE,
            left_document_id=lease.document_id,
            right_document_id=registry.document_id,
            explanation="확인된 근저당이 모두 말소 표시돼 현재 말소 특약 비교를 적용하지 않습니다.",
        )

    clause_found = any(
        "mortgage_cancellation" in clause.categories for clause in lease.special_clauses
    )
    uncertain_clause = any(
        "mortgage_cancellation" in clause.categories
        and clause.status == AnalysisValueStatus.UNCERTAIN
        for clause in lease.special_clauses
    )
    if uncertain_clause:
        status = ComparisonStatus.UNCERTAIN
    elif clause_found:
        status = ComparisonStatus.MATCH
    else:
        status = ComparisonStatus.MISSING
    return ComparisonItem(
        key="mortgage_cancellation_clause",
        label="근저당과 말소 특약",
        status=status,
        left_document_id=lease.document_id,
        right_document_id=registry.document_id,
        left_value=[clause.text for clause in lease.special_clauses],
        right_value=[item.raw_text for item in active_mortgages],
        explanation={
            ComparisonStatus.MATCH: "현재 유효 가능성이 있는 근저당과 관련된 말소 특약 문구를 확인했습니다.",
            ComparisonStatus.UNCERTAIN: "말소 특약으로 보이는 문구가 있으나 OCR 또는 추출값이 불확실합니다.",
            ComparisonStatus.MISSING: "현재 유효 가능성이 있는 근저당은 있으나 말소 특약 문구를 찾지 못했습니다.",
        }[status],
    )


def compare_documents(
    *,
    conversation_id: str,
    lease: LeaseAnalysisResult | None,
    registry: RegistryAnalysisResult | None,
) -> DocumentComparisonResult:
    comparisons: list[ComparisonItem] = []
    triggered: list[str] = []
    warnings: list[str] = []

    if lease is not None and registry is not None:
        owner_comparison = compare_owner_and_lessor(lease, registry)
        address_comparison = compare_addresses(lease, registry)
        mortgage_clause = compare_mortgage_clause(lease, registry)
        comparisons.extend([owner_comparison, address_comparison, mortgage_clause])
        if owner_comparison.status == ComparisonStatus.MISMATCH:
            triggered.append("q03_owner_lessor_mismatch")
        if address_comparison.status == ComparisonStatus.MISMATCH:
            triggered.append("q18_address_mismatch")
    else:
        warnings.append(
            "계약서와 등기부가 모두 있어야 두 문서의 일치 여부를 비교할 수 있습니다."
        )

    if registry is not None:
        co_owner = _field(registry, "co_owner_exists")
        if (
            co_owner is not None
            and co_owner.status == AnalysisValueStatus.CONFIRMED
            and co_owner.value is True
        ):
            triggered.append("q02_co_owner")
        if any(item.active is not False for item in registry.mortgages):
            triggered.append("q07_mortgage")
        if any(item.active is not False for item in registry.restrictions):
            triggered.append("q09_registry_restriction_warning")
        if any(item.active is not False for item in registry.trusts):
            triggered.append("q10_trust")

    if lease is not None and any(
        "deposit_return" in clause.categories for clause in lease.special_clauses
    ):
        triggered.append("q14_special_clause_deposit_return")

    unique_triggered: list[str] = []
    for issue_id in triggered:
        if issue_id not in unique_triggered:
            unique_triggered.append(issue_id)

    return DocumentComparisonResult(
        conversation_id=conversation_id,
        lease_document_id=(lease.document_id if lease else None),
        registry_document_id=(registry.document_id if registry else None),
        comparisons=comparisons,
        triggered_issue_ids=unique_triggered,
        warnings=warnings,
    )
