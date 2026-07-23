"""등기사항전부증명서 추출 텍스트에서 소유자와 권리관계를 분석한다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from app.documents.analysis.field_validation import (
    FieldCandidate,
    build_field,
    candidate,
    make_evidence,
    page_confidence,
)
from app.documents.analysis.models import (
    ANALYSIS_VERSION,
    AnalysisValueStatus,
    AnalyzedField,
    RegistryAnalysisResult,
    RegistryRight,
)
from app.documents.analysis.normalization import (
    address_signal_score,
    compact_ocr_text,
    extract_address_components,
    normalize_amount,
    normalize_date,
    normalize_name,
    normalize_whitespace,
    repair_address_ocr,
)
from app.documents.extraction_models import (
    DocumentExtractionResult,
    PageExtractionResult,
    PageExtractionStatus,
)
from app.documents.models import UploadedDocument, utc_now


@dataclass(frozen=True)
class _Line:
    page: PageExtractionResult
    text: str
    compact: str


FIELD_LABELS: dict[str, str] = {
    "registry_address": "등기부 소재지",
    "issue_date": "등기부 발급·열람일",
    "property_type": "부동산 구분",
    "current_owners": "현재 소유자",
    "ownership_shares": "소유 지분",
    "co_owner_exists": "공동소유 여부",
    "mortgage_exists": "근저당 존재",
    "maximum_secured_amount": "채권최고액",
    "restriction_types": "권리 제한 종류",
    "active_restriction_exists": "현재 유효한 권리 제한",
    "trust_registration_exists": "현재 유효한 신탁등기",
    "trust_cancelled_history": "말소된 신탁등기 이력",
    "section_eul_has_records": "을구 기록 존재 여부",
    "trustees": "수탁자",
    "latest_registry_checked": "등기부 기준일 확인",
}

_ADDRESS_EXPLICIT = re.compile(r"(?:소재지|건물의표시|부동산의표시)[:：]?(.+)$")
_ISSUE_DATE = re.compile(r"(?:발급일|열람일|발행일|열람일시)[:：]?(.+)$")
_OWNER_EXPLICIT = re.compile(
    r"(?:현재)?(?:소유자|공유자)[:：]?([가-힣A-Za-z]{2,30}?)(?=지분|\d{6}|$)"
)
_OWNER_BEFORE_ID = re.compile(r"([가-힣]{2,4})(?=\d{6}-[*0-9])")
_SHARE_PATTERN = re.compile(r"지분[:：]?([0-9분의/]+)")
_AMOUNT_PATTERN = re.compile(r"채권최고액.*?([0-9][0-9,]{4,})")
_DATE_PATTERN = re.compile(
    r"(?:19|20)\d{2}\s*[년./-]\s*\d{1,2}\s*[월./-]\s*\d{1,2}\s*일?"
)
_RESTRICTION_PATTERNS = {
    "가압류": re.compile(r"가압류"),
    "압류": re.compile(r"(?<!가)압류"),
    "가처분": re.compile(r"가처분"),
}


def _compact_registry_text(value: str) -> str:
    compact = compact_ocr_text(value)
    corrections = {
        "산탁": "신탁",
        "산닥": "신탁",
        "신닥": "신탁",
        "산특": "신탁",
        "신특": "신탁",
        "등커": "등기",
        "등카": "등기",
        "등키": "등기",
        "등거": "등기",
        "기룩사항": "기록사항",
        "기록사함": "기록사항",
    }
    for source, target in corrections.items():
        compact = compact.replace(source, target)
    return compact


def _has_trust_marker(value: str) -> bool:
    compact = _compact_registry_text(value)
    return bool(
        "신탁" in compact
        or re.search(r"[신산][탁닥특]", compact)
        or re.search(r"탁등[기카커키]", compact)
    )


def _has_trust_cancellation_marker(value: str) -> bool:
    compact = _compact_registry_text(value)
    return bool(
        "신탁등기말소" in compact
        or "별도등기말소" in compact
        or (_has_trust_marker(compact) and "말소" in compact)
    )


_REGION_MARKERS = (
    "서울특별시",
    "부산광역시",
    "대구광역시",
    "인천광역시",
    "광주광역시",
    "대전광역시",
    "울산광역시",
    "세종특별자치시",
    "경기도",
    "강원특별자치도",
    "충청북도",
    "충청남도",
    "전북특별자치도",
    "전라남도",
    "경상북도",
    "경상남도",
    "제주특별자치도",
    "서울",
    "부산",
    "대구",
    "인천",
    "광주",
    "대전",
    "울산",
    "세종",
    "제주",
)


def _looks_like_registry_address(value: str) -> bool:
    compact = repair_address_ocr(value)
    components = extract_address_components(value)
    has_region = any(marker in compact for marker in _REGION_MARKERS)
    has_location = bool(
        components.get("district")
        and (components.get("neighborhood") or components.get("road"))
    )
    has_unit = bool(components.get("unit"))
    return has_region and has_location and has_unit and address_signal_score(value) >= 7


def _best_owner_candidates(items: list[FieldCandidate]) -> list[FieldCandidate]:
    """같은 소유자 이름이 한글과 영문 OCR로 중복된 경우 한글 후보를 우선한다."""

    if not items:
        return []
    hangul_items = [
        item
        for item in items
        if re.fullmatch(r"[가-힣]{2,30}", str(item.normalized_value))
    ]
    selected = hangul_items or items
    result: list[FieldCandidate] = []
    seen: set[str] = set()
    for item in selected:
        key = str(item.normalized_value).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _best_address_candidates(items: list[FieldCandidate]) -> list[FieldCandidate]:
    if not items:
        return []
    usable = [item for item in items if _looks_like_registry_address(item.raw_value)]
    if not usable:
        return []
    best_score = max(address_signal_score(item.raw_value) for item in usable)
    selected = [
        item for item in usable if address_signal_score(item.raw_value) == best_score
    ]
    # 같은 주소가 OCR 중복 스캔으로 반복된 경우 첫 근거만 남긴다.
    unique: list[FieldCandidate] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for item in selected:
        components = extract_address_components(item.raw_value)
        key = tuple(sorted(components.items()))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:1]


def _page_compact_text(lines: list[_Line], page_number: int) -> str:
    return "".join(
        item.compact for item in lines if item.page.page_number == page_number
    )


def _page_lines(extraction: DocumentExtractionResult) -> list[_Line]:
    result: list[_Line] = []
    for page in extraction.pages:
        if page.status != PageExtractionStatus.COMPLETED:
            continue
        for raw_line in page.text.splitlines():
            line = normalize_whitespace(raw_line)
            if line:
                result.append(
                    _Line(
                        page=page,
                        text=line,
                        compact=_compact_registry_text(line),
                    )
                )
    return result


def _candidate(
    *,
    document_id: str,
    line: _Line,
    raw_value: str,
    normalizer,
) -> FieldCandidate | None:
    return candidate(
        document_id=document_id,
        page=line.page,
        raw_value=raw_value,
        evidence_text=line.text,
        normalizer=normalizer,
    )


def _context(lines: list[_Line], index: int, radius: int = 3) -> str:
    page_number = lines[index].page.page_number
    selected: list[str] = []
    for current in lines[index : index + radius + 1]:
        if current.page.page_number != page_number:
            break
        selected.append(current.text)
    return " ".join(selected)


def _active_from_text(text: str) -> tuple[bool | None, str | None]:
    normalized = _compact_registry_text(text)
    if "말소" in normalized or "말소등기" in normalized:
        return False, "cancelled"
    if "현재유효" in normalized or "유효" in normalized:
        return True, "active"
    return None, "unknown"


def _right_confidence(line: _Line) -> float:
    return page_confidence(line.page)


def _boolean_field(
    *,
    key: str,
    value: bool | None,
    line: _Line | None,
    document_id: str,
    uncertain: bool = False,
    warning: str | None = None,
) -> AnalyzedField:
    if line is None or value is None:
        return AnalyzedField(key=key, label=FIELD_LABELS[key])
    confidence = page_confidence(line.page)
    warnings: list[str] = []
    if warning:
        warnings.append(warning)
    if line.page.extraction_method.value == "ocr" and confidence < 0.85:
        warnings.append("OCR 평균 신뢰도가 85% 미만입니다.")
    status = (
        AnalysisValueStatus.UNCERTAIN
        if uncertain or confidence < 0.85
        else AnalysisValueStatus.CONFIRMED
    )
    return AnalyzedField(
        key=key,
        label=FIELD_LABELS[key],
        status=status,
        value=value,
        raw_values=[str(value).lower()],
        confidence=confidence,
        evidences=[
            make_evidence(
                document_id=document_id,
                page=line.page,
                text=line.text,
            )
        ],
        warnings=warnings,
    )


def _find_current_document_line(lines: list[_Line]) -> _Line | None:
    return next(
        (
            line
            for line in lines
            if "현재유효사항" in line.compact or "등기사항전부증명서" in line.compact
        ),
        lines[0] if lines else None,
    )


def analyze_registry(
    *,
    document: UploadedDocument,
    extraction: DocumentExtractionResult,
) -> RegistryAnalysisResult:
    started_at = utc_now()
    lines = _page_lines(extraction)
    candidates: dict[str, list[FieldCandidate]] = {key: [] for key in FIELD_LABELS}
    mortgages: list[RegistryRight] = []
    restrictions: list[RegistryRight] = []
    trusts: list[RegistryRight] = []
    current_doc_line = _find_current_document_line(lines)

    for index, line in enumerate(lines):
        compact = line.compact

        explicit_address = _ADDRESS_EXPLICIT.search(compact)
        if explicit_address:
            raw_address = explicit_address.group(1)
            if _looks_like_registry_address(raw_address):
                item = _candidate(
                    document_id=document.document_id,
                    line=line,
                    raw_value=raw_address,
                    normalizer=normalize_whitespace,
                )
                if item:
                    candidates["registry_address"].append(item)

        if (
            any(marker in compact for marker in _REGION_MARKERS)
            and re.search(r"(?:제)?\d{1,5}호", repair_address_ocr(line.text))
            and _looks_like_registry_address(line.text)
        ):
            raw = re.sub(r"^.*?집합건물[\]】)]?", "", line.text).strip()
            if _looks_like_registry_address(raw):
                item = _candidate(
                    document_id=document.document_id,
                    line=line,
                    raw_value=raw,
                    normalizer=normalize_whitespace,
                )
                if item:
                    candidates["registry_address"].append(item)

        issue_match = _ISSUE_DATE.search(compact)
        if issue_match:
            date_match = _DATE_PATTERN.search(line.text)
            raw_date = date_match.group(0) if date_match else issue_match.group(1)
            item = _candidate(
                document_id=document.document_id,
                line=line,
                raw_value=raw_date,
                normalizer=normalize_date,
            )
            if item:
                candidates["issue_date"].append(item)
                issue_date = date.fromisoformat(str(item.normalized_value))
                age_days = (utc_now().date() - issue_date).days
                is_recent = 0 <= age_days <= 7
                latest_warnings = list(item.warnings)
                if age_days < 0:
                    latest_warnings.append(
                        "등기부 발급·열람일이 분석일보다 미래입니다."
                    )
                elif age_days > 7:
                    latest_warnings.append(
                        "등기부 발급·열람일이 분석일 기준 7일을 초과했습니다."
                    )
                candidates["latest_registry_checked"].append(
                    FieldCandidate(
                        raw_value=raw_date,
                        normalized_value=is_recent,
                        evidence=item.evidence,
                        confidence=item.confidence,
                        warnings=tuple(latest_warnings),
                    )
                )

        if "집합건물" in compact:
            item = _candidate(
                document_id=document.document_id,
                line=line,
                raw_value="집합건물",
                normalizer=normalize_whitespace,
            )
            if item:
                candidates["property_type"].append(item)

        owner_context = _compact_registry_text(_context(lines, index, radius=5))
        owner_source = compact
        if "소유자" not in owner_source and "소유권이전" in compact:
            owner_source = owner_context
        owner_match = _OWNER_EXPLICIT.search(owner_source)
        if owner_match and not any(
            marker in owner_source for marker in ("수탁자", "채권자", "근저당권자")
        ):
            raw_owner = owner_match.group(1)
            if raw_owner not in {"이외", "관한사항", "기록사항"}:
                item = _candidate(
                    document_id=document.document_id,
                    line=line,
                    raw_value=raw_owner,
                    normalizer=normalize_name,
                )
                if item:
                    candidates["current_owners"].append(item)
        elif "소유권이전" in owner_source:
            owner_by_id = re.search(
                r"(?:소유자)?([가-힣]{2,4})(?=\d{6}-[*0-9]|\d{6}|서울|경기|부산|대구|인천)",
                owner_source,
            )
            if owner_by_id:
                raw_owner = owner_by_id.group(1)
                invalid_owner_tokens = (
                    "매매",
                    "소유",
                    "이전",
                    "서울",
                    "경기",
                    "신탁",
                    "말소",
                    "접수",
                    "등기",
                    "사항",
                    "권리",
                )
                if not any(token in raw_owner for token in invalid_owner_tokens):
                    item = _candidate(
                        document_id=document.document_id,
                        line=line,
                        raw_value=raw_owner,
                        normalizer=normalize_name,
                    )
                    if item:
                        candidates["current_owners"].append(item)

        for share in _SHARE_PATTERN.finditer(compact):
            item = _candidate(
                document_id=document.document_id,
                line=line,
                raw_value=share.group(1),
                normalizer=normalize_whitespace,
            )
            if item:
                candidates["ownership_shares"].append(item)

        context = _context(lines, index)
        compact_context = _compact_registry_text(context)

        if "근저당권" in compact:
            amount_match = _AMOUNT_PATTERN.search(compact_context)
            date_match = _DATE_PATTERN.search(context)
            holder_match = re.search(
                r"(?:근저당권자|채권자)[:：]?([^,，\n]+?)(?=(?:채권최고액|설정일|접수|$))",
                compact_context,
            )
            active, cancellation = _active_from_text(context)
            right = RegistryRight(
                right_type="mortgage",
                holder=(
                    normalize_whitespace(holder_match.group(1))
                    if holder_match
                    else None
                ),
                amount=(
                    normalize_amount(amount_match.group(1)) if amount_match else None
                ),
                registration_date=(
                    normalize_date(date_match.group(0)) if date_match else None
                ),
                active=active,
                cancellation_status=cancellation,
                raw_text=context,
                page_number=line.page.page_number,
                extraction_method=line.page.extraction_method.value,
                confidence=_right_confidence(line),
                warnings=(
                    []
                    if _right_confidence(line) >= 0.85
                    else ["근저당 OCR 신뢰도가 낮습니다."]
                ),
            )
            if not any(current.raw_text == right.raw_text for current in mortgages):
                mortgages.append(right)
            if amount_match:
                item = _candidate(
                    document_id=document.document_id,
                    line=line,
                    raw_value=amount_match.group(1),
                    normalizer=normalize_amount,
                )
                if item:
                    candidates["maximum_secured_amount"].append(item)

        for restriction_type, restriction_pattern in _RESTRICTION_PATTERNS.items():
            if not restriction_pattern.search(compact):
                continue
            date_match = _DATE_PATTERN.search(context)
            active, cancellation = _active_from_text(context)
            right = RegistryRight(
                right_type=restriction_type,
                registration_date=(
                    normalize_date(date_match.group(0)) if date_match else None
                ),
                active=active,
                cancellation_status=cancellation,
                raw_text=context,
                page_number=line.page.page_number,
                extraction_method=line.page.extraction_method.value,
                confidence=_right_confidence(line),
                warnings=(
                    []
                    if _right_confidence(line) >= 0.85
                    else ["권리 제한 OCR 신뢰도가 낮습니다."]
                ),
            )
            if not any(
                current.right_type == right.right_type
                and current.raw_text == right.raw_text
                for current in restrictions
            ):
                restrictions.append(right)
            type_candidate = _candidate(
                document_id=document.document_id,
                line=line,
                raw_value=restriction_type,
                normalizer=normalize_whitespace,
            )
            if type_candidate:
                candidates["restriction_types"].append(type_candidate)

        if _has_trust_marker(compact):
            date_match = _DATE_PATTERN.search(context)
            active, cancellation = _active_from_text(context)
            if _has_trust_cancellation_marker(compact_context):
                active, cancellation = False, "cancelled"
            holder_match = re.search(
                r"수탁자[:：]?([^,，\n]+?)(?=(?:접수일|접수|등기|$))",
                compact_context,
            )
            right = RegistryRight(
                right_type="trust",
                holder=(
                    normalize_whitespace(holder_match.group(1))
                    if holder_match
                    else None
                ),
                registration_date=(
                    normalize_date(date_match.group(0)) if date_match else None
                ),
                active=active,
                cancellation_status=cancellation,
                raw_text=context,
                page_number=line.page.page_number,
                extraction_method=line.page.extraction_method.value,
                confidence=_right_confidence(line),
                warnings=(
                    []
                    if _right_confidence(line) >= 0.85
                    else ["신탁 OCR 신뢰도가 낮습니다."]
                ),
            )
            if not any(current.raw_text == right.raw_text for current in trusts):
                trusts.append(right)
            if holder_match:
                trustee = _candidate(
                    document_id=document.document_id,
                    line=line,
                    raw_value=holder_match.group(1),
                    normalizer=normalize_whitespace,
                )
                if trustee:
                    candidates["trustees"].append(trustee)

    cancelled_trust_pages = {
        item.page_number for item in trusts if item.active is False
    }
    for page_number in sorted({line.page.page_number for line in lines}):
        page_text = _page_compact_text(lines, page_number)
        has_trust = _has_trust_marker(page_text)
        has_cancellation = _has_trust_cancellation_marker(page_text)
        if has_trust and has_cancellation:
            cancelled_trust_pages.add(page_number)
    lines_by_page: dict[int, list[_Line]] = {}
    for current_line in lines:
        lines_by_page.setdefault(current_line.page.page_number, []).append(current_line)
    for page_number, page_lines in lines_by_page.items():
        page_has_trust = any(_has_trust_marker(item.compact) for item in page_lines)
        page_has_separate_cancellation = any(
            _has_trust_cancellation_marker(item.compact) for item in page_lines
        )
        if page_has_trust and page_has_separate_cancellation:
            cancelled_trust_pages.add(page_number)

    for page_number in sorted(cancelled_trust_pages):
        if any(item.page_number == page_number for item in trusts):
            continue
        page_lines = lines_by_page.get(page_number, [])
        source = next(
            (
                item
                for item in page_lines
                if _has_trust_marker(item.compact)
                or _has_trust_cancellation_marker(item.compact)
            ),
            page_lines[0] if page_lines else None,
        )
        if source is None:
            continue
        context = " ".join(item.text for item in page_lines)
        date_match = _DATE_PATTERN.search(context)
        trusts.append(
            RegistryRight(
                right_type="trust",
                registration_date=(
                    normalize_date(date_match.group(0)) if date_match else None
                ),
                active=False,
                cancellation_status="cancelled",
                raw_text=context,
                page_number=page_number,
                extraction_method=source.page.extraction_method.value,
                confidence=_right_confidence(source),
                warnings=(
                    []
                    if _right_confidence(source) >= 0.85
                    else ["신탁 말소 OCR 신뢰도가 낮습니다."]
                ),
            )
        )

    if cancelled_trust_pages:
        trusts = [
            item.model_copy(
                update={
                    "active": False,
                    "cancellation_status": "cancelled",
                }
            )
            if item.active is None and item.page_number in cancelled_trust_pages
            else item
            for item in trusts
        ]

    candidates["registry_address"] = _best_address_candidates(
        candidates["registry_address"]
    )
    candidates["current_owners"] = _best_owner_candidates(candidates["current_owners"])
    owner_field = build_field(
        key="current_owners",
        label=FIELD_LABELS["current_owners"],
        candidates=candidates["current_owners"],
        multi_value=True,
    )
    owner_count = (
        len(owner_field.value or []) if isinstance(owner_field.value, list) else 0
    )
    co_owner_marker = any(
        "공유자" in _compact_registry_text(item.evidence.text)
        or "지분" in _compact_registry_text(item.evidence.text)
        for item in candidates["current_owners"]
    )
    if owner_count == 1:
        owner_evidence = candidates["current_owners"][0]
        candidates["co_owner_exists"].append(
            FieldCandidate(
                raw_value="false",
                normalized_value=False,
                evidence=owner_evidence.evidence,
                confidence=owner_evidence.confidence,
                warnings=owner_evidence.warnings,
            )
        )
    elif owner_count > 1 and co_owner_marker:
        owner_evidence = candidates["current_owners"][0]
        candidates["co_owner_exists"].append(
            FieldCandidate(
                raw_value="true",
                normalized_value=True,
                evidence=owner_evidence.evidence,
                confidence=owner_evidence.confidence,
                warnings=owner_evidence.warnings,
            )
        )

    active_mortgages = [item for item in mortgages if item.active is True]
    unknown_mortgages = [item for item in mortgages if item.active is None]
    active_restrictions = [item for item in restrictions if item.active is True]
    unknown_restrictions = [item for item in restrictions if item.active is None]
    active_trusts = [item for item in trusts if item.active is True]
    unknown_trusts = [item for item in trusts if item.active is None]
    cancelled_trusts = [item for item in trusts if item.active is False]

    eul_markers = (
        "을구",
        "소유권이외의권리에관한사항",
        "소유권이의의권리에관한사항",
    )
    eul_line = next(
        (
            line
            for line in lines
            if any(marker in line.compact for marker in eul_markers)
        ),
        None,
    )
    eul_page_number = eul_line.page.page_number if eul_line else None
    if eul_page_number is None:
        for page_number in sorted({line.page.page_number for line in lines}):
            page_text = _page_compact_text(lines, page_number)
            if "기록사항없음" in page_text and (
                "소유권" in page_text or "관한사항" in page_text
            ):
                eul_page_number = page_number
                break
    no_records_line = next(
        (
            line
            for line in lines
            if "기록사항없음" in line.compact
            and (eul_page_number is None or line.page.page_number == eul_page_number)
        ),
        None,
    )
    completed_pages = {
        page.page_number
        for page in extraction.pages
        if page.status == PageExtractionStatus.COMPLETED
    }
    expected_pages = set(range(1, extraction.page_count + 1))
    current_document_marker = any(
        "현재유효사항" in line.compact or "등기사항전부증명서" in line.compact
        for line in lines
    )
    ownership_structure_marker = bool(owner_field.value) and any(
        marker in line.compact
        for line in lines
        for marker in (
            "소유권이전",
            "소유권에관한사항",
            "갑구",
            "소유자",
        )
    )
    full_current_registry = bool(
        extraction.page_count >= 3
        and completed_pages == expected_pages
        and current_document_marker
        and ownership_structure_marker
        and no_records_line is not None
    )

    fields = {
        key: (
            owner_field
            if key == "current_owners"
            else build_field(
                key=key,
                label=FIELD_LABELS[key],
                candidates=items,
                multi_value=key
                in {
                    "ownership_shares",
                    "restriction_types",
                    "trustees",
                },
            )
        )
        for key, items in candidates.items()
    }

    if owner_count > 1 and not co_owner_marker:
        fields["co_owner_exists"] = AnalyzedField(
            key="co_owner_exists",
            label=FIELD_LABELS["co_owner_exists"],
            status=AnalysisValueStatus.UNCERTAIN,
            value=None,
            raw_values=[str(value) for value in (owner_field.value or [])],
            confidence=owner_field.confidence,
            evidences=owner_field.evidences,
            warnings=[
                "여러 이름이 인식됐지만 공유자·지분 근거가 없어 공동소유로 확정하지 않습니다."
            ],
        )

    if active_mortgages:
        source = next(line for line in lines if "근저당권" in line.compact)
        fields["mortgage_exists"] = _boolean_field(
            key="mortgage_exists",
            value=True,
            line=source,
            document_id=document.document_id,
        )
    elif unknown_mortgages:
        source = next(line for line in lines if "근저당권" in line.compact)
        fields["mortgage_exists"] = _boolean_field(
            key="mortgage_exists",
            value=True,
            line=source,
            document_id=document.document_id,
            uncertain=True,
            warning="근저당 문구는 확인했지만 현재 유효 여부를 확정하지 못했습니다.",
        )
    elif no_records_line:
        fields["mortgage_exists"] = _boolean_field(
            key="mortgage_exists",
            value=False,
            line=no_records_line,
            document_id=document.document_id,
        )

    if active_restrictions:
        source = next(
            line
            for line in lines
            if any(item.right_type in line.compact for item in active_restrictions)
        )
        fields["active_restriction_exists"] = _boolean_field(
            key="active_restriction_exists",
            value=True,
            line=source,
            document_id=document.document_id,
        )
    elif unknown_restrictions:
        source = next(
            line
            for line in lines
            if any(item.right_type in line.compact for item in unknown_restrictions)
        )
        fields["active_restriction_exists"] = _boolean_field(
            key="active_restriction_exists",
            value=True,
            line=source,
            document_id=document.document_id,
            uncertain=True,
            warning="권리 제한 문구는 확인했지만 현재 유효 여부를 확정하지 못했습니다.",
        )
    elif full_current_registry and not restrictions:
        source = next(
            (line for line in lines if "소유권이전" in line.compact),
            current_doc_line or no_records_line,
        )
        fields["active_restriction_exists"] = _boolean_field(
            key="active_restriction_exists",
            value=False,
            line=source,
            document_id=document.document_id,
            warning=(
                "현재 유효사항 전체 페이지와 갑구·을구 구조를 확인한 범위에서 "
                "압류·가압류·가처분 문구가 없습니다."
            ),
        )

    if active_trusts:
        source = next(line for line in lines if _has_trust_marker(line.compact))
        fields["trust_registration_exists"] = _boolean_field(
            key="trust_registration_exists",
            value=True,
            line=source,
            document_id=document.document_id,
        )
    elif unknown_trusts:
        source = next(line for line in lines if _has_trust_marker(line.compact))
        fields["trust_registration_exists"] = _boolean_field(
            key="trust_registration_exists",
            value=True,
            line=source,
            document_id=document.document_id,
            uncertain=True,
            warning="신탁 문구는 확인했지만 말소 여부를 확정하지 못했습니다.",
        )
    elif cancelled_trusts:
        source = next(line for line in lines if _has_trust_marker(line.compact))
        fields["trust_registration_exists"] = _boolean_field(
            key="trust_registration_exists",
            value=False,
            line=source,
            document_id=document.document_id,
        )

    if cancelled_trusts:
        source = next(
            (
                line
                for line in lines
                if _has_trust_marker(line.compact)
                or _has_trust_cancellation_marker(line.compact)
            ),
            current_doc_line,
        )
        fields["trust_cancelled_history"] = _boolean_field(
            key="trust_cancelled_history",
            value=True,
            line=source,
            document_id=document.document_id,
        )
    elif full_current_registry and any(
        _has_trust_cancellation_marker(_page_compact_text(lines, page_number))
        for page_number in completed_pages
    ):
        source = next(
            line for line in lines if _has_trust_cancellation_marker(line.compact)
        )
        fields["trust_registration_exists"] = _boolean_field(
            key="trust_registration_exists",
            value=False,
            line=source,
            document_id=document.document_id,
        )
        fields["trust_cancelled_history"] = _boolean_field(
            key="trust_cancelled_history",
            value=True,
            line=source,
            document_id=document.document_id,
        )

    if no_records_line:
        fields["section_eul_has_records"] = _boolean_field(
            key="section_eul_has_records",
            value=False,
            line=eul_line or no_records_line,
            document_id=document.document_id,
        )
    elif mortgages:
        source = next(line for line in lines if "근저당권" in line.compact)
        fields["section_eul_has_records"] = _boolean_field(
            key="section_eul_has_records",
            value=True,
            line=source,
            document_id=document.document_id,
        )

    warnings: list[str] = []
    if not lines:
        warnings.append("분석할 수 있는 성공 페이지 텍스트가 없습니다.")
    if fields["current_owners"].status == AnalysisValueStatus.UNKNOWN:
        warnings.append("현재 소유자를 확인하지 못했습니다.")
    if fields["registry_address"].status == AnalysisValueStatus.UNKNOWN:
        warnings.append("등기부 소재지를 확인하지 못했습니다.")
    if unknown_mortgages or unknown_restrictions or unknown_trusts:
        warnings.append("일부 권리의 현재 유효·말소 여부를 확정하지 못했습니다.")

    return RegistryAnalysisResult(
        analysis_version=ANALYSIS_VERSION,
        document_id=document.document_id,
        conversation_id=document.conversation_id,
        source_sha256=document.sha256,
        source_extraction_version=extraction.extraction_version,
        fields=fields,
        mortgages=mortgages,
        restrictions=restrictions,
        trusts=trusts,
        warnings=warnings,
        started_at=started_at,
        completed_at=utc_now(),
    )
