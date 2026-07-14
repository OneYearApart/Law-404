"""임대차계약서 추출 텍스트에서 핵심 필드와 특약을 분석한다."""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.documents.analysis.field_validation import (
    FieldCandidate,
    build_field,
    candidate,
    page_confidence,
)
from backend.app.documents.analysis.models import (
    ANALYSIS_VERSION,
    AnalysisValueStatus,
    LeaseAnalysisResult,
    SpecialClause,
)
from backend.app.documents.analysis.normalization import (
    compact_ocr_text,
    normalize_amount,
    normalize_date,
    normalize_name,
    normalize_text_value,
    normalize_whitespace,
)
from backend.app.documents.extraction_models import (
    DocumentExtractionResult,
    PageExtractionResult,
    PageExtractionStatus,
)
from backend.app.documents.models import UploadedDocument, utc_now


@dataclass(frozen=True)
class _Line:
    page: PageExtractionResult
    text: str
    compact: str


FIELD_LABELS: dict[str, str] = {
    "lessor_name": "임대인",
    "lessee_name": "임차인",
    "representative_name": "대리인",
    "property_address": "임대차 목적물 주소",
    "deposit_amount": "보증금",
    "contract_payment": "계약금",
    "interim_payment": "중도금",
    "balance_payment": "잔금",
    "monthly_rent": "월 차임",
    "maintenance_fee": "관리비",
    "contract_date": "계약 체결일",
    "move_in_date": "입주일",
    "contract_start_date": "계약 시작일",
    "contract_end_date": "계약 종료일",
    "housing_type": "주택 유형",
    "lessor_signature_marker": "임대인 서명·날인 문구",
    "lessee_signature_marker": "임차인 서명·날인 문구",
    "broker_signature_marker": "중개사 서명·날인 문구",
    "special_clause_text": "특약 원문",
}


_NAME_SUFFIX = r"(?=서명|날인|주민|생년|전화|주소|$)"
_NAME_PATTERNS = {
    "lessor_name": re.compile(
        rf"(?:임대인성명[:：|]?|임대인[:：|]|매도인성명[:：|]?|매도인[:：|])"
        rf"([가-힣A-Za-z]{{2,30}}?){_NAME_SUFFIX}"
    ),
    "lessee_name": re.compile(
        rf"(?:임차인성명[:：|]?|임차인[:：|]|매수인성명[:：|]?|매수인[:：|])"
        rf"([가-힣A-Za-z]{{2,30}}?){_NAME_SUFFIX}"
    ),
    "representative_name": re.compile(
        rf"(?:대리인성명[:：|]?|대리인[:：|])"
        rf"([가-힣A-Za-z]{{2,30}}?){_NAME_SUFFIX}"
    ),
}
_AMOUNT_LABEL_PATTERNS = {
    "deposit_amount": re.compile(r"(?:전세)?보증금.*?([0-9][0-9,]{4,})"),
    "contract_payment": re.compile(r"계약금.*?([0-9][0-9,]{4,})"),
    "interim_payment": re.compile(r"중도금.*?([0-9][0-9,]{4,})"),
    "balance_payment": re.compile(r"잔금.*?([0-9][0-9,]{4,})"),
    "monthly_rent": re.compile(r"(?:월차임|월세).*?([0-9][0-9,]{2,})"),
    "maintenance_fee": re.compile(r"관리비.*?([0-9][0-9,]{2,})"),
}
_SIGNATURE_PATTERNS = {
    "lessor_signature_marker": re.compile(r"임대인.{0,40}(?:서명|날인|\(인\)|印)"),
    "lessee_signature_marker": re.compile(r"임차인.{0,40}(?:서명|날인|\(인\)|印)"),
    "broker_signature_marker": re.compile(r"(?:공인중개사|중개업자).{0,40}(?:서명|날인|\(인\)|印)"),
}
_CLAUSE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "mortgage_cancellation": ("근저당", "말소"),
    "deposit_return": ("계약금", "반환"),
    "guarantee": ("보증보험", "반환보증"),
    "repair": ("수리", "하자", "보수"),
    "third_party_account": ("제3자", "계좌", "예금주"),
    "restoration": ("원상복구",),
}
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
)
_DATE_TOKEN = re.compile(
    r"(?:19|20)\d{2}\s*[년./-]\s*\d{1,2}\s*[월./-]\s*\d{1,2}\s*일?"
)
_OCR_COMPACT_DATE_TOKEN = re.compile(
    r"(?P<year>20\d{2}|19\d{2})[6G년]"
    r"(?P<month>1[0-2]|0?[1-9])[8B월]"
    r"(?P<day>3[01]|[12]\d|0?[1-9])[2Z일](?!\d)",
    re.IGNORECASE,
)
_MONEY_TOKEN = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+)(?!\d)")


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
                        compact=compact_ocr_text(line),
                    )
                )
    return result


def _text_candidate(
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


def _categories(text: str) -> list[str]:
    normalized = compact_ocr_text(normalize_text_value(text))
    result: list[str] = []
    for category, keywords in _CLAUSE_KEYWORDS.items():
        if all(compact_ocr_text(keyword) in normalized for keyword in keywords):
            result.append(category)
        elif category in {"guarantee", "repair", "restoration"} and any(
            compact_ocr_text(keyword) in normalized for keyword in keywords
        ):
            result.append(category)
    return result


def _special_clauses(
    *,
    lines: list[_Line],
) -> list[SpecialClause]:
    start_index: int | None = None
    for index, item in enumerate(lines):
        compact = item.compact.lower()
        if "특약사항" in compact or "득약사항" in compact:
            start_index = index + 1
            break
        if (
            index > len(lines) // 3
            and re.match(r"^1[.．]", item.text.strip())
            and "현시설물" in compact
        ):
            start_index = index
            break

    if start_index is None:
        return []

    clauses: list[SpecialClause] = []
    current_text: list[str] = []
    current_page: PageExtractionResult | None = None

    def flush() -> None:
        nonlocal current_text, current_page
        if not current_text or current_page is None:
            current_text = []
            current_page = None
            return
        text = normalize_whitespace(" ".join(current_text))
        confidence = page_confidence(current_page)
        clauses.append(
            SpecialClause(
                text=text,
                page_number=current_page.page_number,
                categories=_categories(text),
                extraction_method=current_page.extraction_method.value,
                confidence=confidence,
                status=(
                    AnalysisValueStatus.CONFIRMED
                    if confidence >= 0.85
                    else AnalysisValueStatus.UNCERTAIN
                ),
            )
        )
        current_text = []
        current_page = None

    for item in lines[start_index:]:
        compact = item.compact.lower()
        if any(
            marker in compact
            for marker in (
                "임대인계좌번호",
                "이하여백",
                "본계약을증명",
                "주민등록번호",
            )
        ):
            flush()
            break

        numbered = re.match(r"^\s*([0-9]{1,2})\s*[.．)]\s*(.+)$", item.text)
        if numbered:
            flush()
            current_page = item.page
            current_text = [numbered.group(2)]
            continue

        if current_text and len(item.text) >= 3:
            current_text.append(item.text)
        elif len(item.text) >= 3:
            current_page = item.page
            current_text = [item.text]

    flush()
    return clauses


_INVALID_PARTY_NAMES = {
    "성명",
    "서명",
    "날인",
    "대표자",
    "임대인",
    "임차인",
    "공인중개사",
    "소속공인",
    "전화",
    "전화번호",
    "번호",
    "등록번호",
    "주민등록",
    "주민등록번호",
    "주소",
}


_INVALID_PARTY_LOCATION_NAMES = {
    normalize_name(marker)
    for marker in _REGION_MARKERS
}


def _is_invalid_party_name(value: str | None) -> bool:
    normalized = normalize_name(value or "")
    date_marker_count = sum(
        marker in normalized for marker in ("년", "월", "일")
    )
    return (
        not normalized
        or normalized in _INVALID_PARTY_NAMES
        or normalized in _INVALID_PARTY_LOCATION_NAMES
        or any(token in normalized for token in _INVALID_PARTY_NAMES)
        or any(
            marker in normalized
            for marker in (
                "특별시",
                "광역시",
                "특별자치시",
                "특별자치도",
            )
        )
        or date_marker_count >= 2
    )


def _party_table_names(lines: list[_Line]) -> list[tuple[_Line, str]]:
    """계약서 하단 당사자 표에서 임대인·임차인 이름을 순서대로 찾는다.

    촬영 이미지에서는 `성명`과 실제 이름이 서로 다른 OCR 줄로 분리될 수 있다.
    이름 주변에 중개사 표기가 있으면 당사자 후보에서 제외한다.
    """

    start_index = 0
    for index, line in enumerate(lines):
        if "본계약을증명" in line.compact or "기명날인" in line.compact:
            start_index = index
            break
    search_lines = lines[start_index:]
    result: list[tuple[_Line, str]] = []
    seen: set[str] = set()

    for offset, line in enumerate(search_lines):
        if "성명" not in line.compact:
            continue
        absolute_index = start_index + offset
        nearby_before = "".join(
            item.compact
            for item in lines[max(0, absolute_index - 4) : absolute_index + 1]
        )
        context = "".join(
            item.compact
            for item in lines[max(0, absolute_index - 3) : absolute_index + 4]
        )
        party_identity_context = bool(
            "주민등록번호" in nearby_before
            or re.search(r"01[016789]\d{7,8}", nearby_before)
        )
        if not party_identity_context and any(
            marker in context
            for marker in (
                "공인중개사",
                "소속공인중개사",
                "대표자명",
                "사무소명칭",
            )
        ):
            continue

        names: list[tuple[_Line, str]] = []
        direct = re.search(r"성명[:：|]?([가-힣]{2,4})(?=$|[^가-힣])", line.compact)
        if direct:
            names.append((line, direct.group(1)))
        else:
            for next_index in range(
                absolute_index + 1,
                min(len(lines), absolute_index + 7),
            ):
                next_line = lines[next_index]
                next_context = "".join(
                    item.compact
                    for item in lines[
                        max(0, next_index - 2) : min(len(lines), next_index + 3)
                    ]
                )
                if not party_identity_context and any(
                    marker in next_context
                    for marker in (
                        "공인중개사",
                        "소속공인중개사",
                        "대표자명",
                        "사무소명칭",
                    )
                ):
                    break
                hangul = re.sub(r"[^가-힣]", "", next_line.text)
                if not 2 <= len(hangul) <= 4:
                    continue
                if _is_invalid_party_name(hangul):
                    continue
                names.append((next_line, hangul))
                break

        for name_line, raw_name in names:
            normalized = normalize_name(raw_name)
            if (
                _is_invalid_party_name(normalized)
                or normalized in seen
            ):
                continue
            seen.add(normalized)
            result.append((name_line, raw_name))
    return result


def _role_nearby_name(
    lines: list[_Line],
    *,
    role_marker: str,
    excluded_names: set[str] | None = None,
) -> tuple[_Line, str] | None:
    """당사자 표의 OCR 순서가 흔들려도 역할 주변에서 이름을 찾는다.

    특정 사람 이름을 알지 못한 상태에서 역할 표기, `성명` 표기, 표 하단 위치,
    주소·등록번호·중개사 문맥을 함께 점수화한다.
    """
    excluded = {normalize_name(item) for item in (excluded_names or set())}
    start_index = next(
        (
            index
            for index, line in enumerate(lines)
            if "본계약을증명" in line.compact or "기명날인" in line.compact
        ),
        max(0, len(lines) // 2),
    )
    role_indexes = [
        index
        for index in range(start_index, len(lines))
        if role_marker in lines[index].compact
    ]
    candidates: list[tuple[int, int, _Line, str]] = []

    for index in range(start_index, len(lines)):
        line = lines[index]
        compact = line.compact
        context = "".join(
            item.compact
            for item in lines[max(start_index, index - 2) : min(len(lines), index + 3)]
        )
        if any(
            marker in context
            for marker in (
                "공인중개사",
                "소속공인중개사",
                "사무소명칭",
                "대표자명",
            )
        ):
            continue
        if any(marker in compact for marker in _REGION_MARKERS):
            continue
        if any(
            marker in compact
            for marker in (
                "주민등록번호",
                "등록번호",
                "전화번호",
                "계좌번호",
                "소재지",
            )
        ):
            continue

        near_name_label = any(
            "성명" in lines[nearby].compact
            for nearby in range(
                max(start_index, index - 2),
                min(len(lines), index + 3),
            )
        )
        if not near_name_label:
            continue

        for match in re.finditer(r"[가-힣]{2,4}", line.text):
            raw_name = match.group(0)
            normalized = normalize_name(raw_name)
            if normalized in excluded or _is_invalid_party_name(normalized):
                continue
            if normalized.endswith(("특별시", "광역시", "자치시", "자치도", "시", "군", "구", "읍", "면", "리")):
                continue

            score = 0
            nearest_role = min(
                (abs(index - role_index) for role_index in role_indexes),
                default=99,
            )
            if nearest_role == 0:
                score += 9
            elif nearest_role == 1:
                score += 7
            elif nearest_role <= 3:
                score += 5
            elif nearest_role <= 7:
                score += 2
            if "성명" in compact:
                score += 5
            if any(
                "성명" in lines[nearby].compact
                for nearby in range(max(start_index, index - 2), min(len(lines), index + 3))
            ):
                score += 3
            if role_marker in context:
                score += 4
            if index >= len(lines) * 2 // 3:
                score += 1
            candidates.append((score, -nearest_role, line, raw_name))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    _, _, line, name = candidates[0]
    return line, name


def _add_name_candidates(
    *,
    document_id: str,
    lines: list[_Line],
    candidates: dict[str, list[FieldCandidate]],
) -> None:
    for line in lines:
        for key, pattern in _NAME_PATTERNS.items():
            match = pattern.search(line.compact)
            if not match:
                continue
            raw_name = match.group(1)
            if _is_invalid_party_name(raw_name):
                continue
            item = _text_candidate(
                document_id=document_id,
                line=line,
                raw_value=raw_name,
                normalizer=normalize_name,
            )
            if item:
                candidates[key].append(item)

    if not candidates["lessor_name"]:
        for line in lines:
            if "임대인계좌번호" not in line.compact:
                continue
            match = re.search(r"[/／]([가-힣]{2,4})(?:$|[^가-힣])", line.compact)
            if match:
                item = _text_candidate(
                    document_id=document_id,
                    line=line,
                    raw_value=match.group(1),
                    normalizer=normalize_name,
                )
                if item:
                    candidates["lessor_name"].append(item)
                    break

    unique_names = _party_table_names(lines)

    if not candidates["lessor_name"] and unique_names:
        line, name = unique_names[0]
        item = _text_candidate(
            document_id=document_id,
            line=line,
            raw_value=name,
            normalizer=normalize_name,
        )
        if item:
            candidates["lessor_name"].append(item)

    lessor_values = {
        str(item.normalized_value) for item in candidates["lessor_name"]
    }
    if not candidates["lessor_name"]:
        fallback_lessor = _role_nearby_name(
            lines,
            role_marker="임대인",
        )
        if fallback_lessor is not None:
            line, name = fallback_lessor
            item = _text_candidate(
                document_id=document_id,
                line=line,
                raw_value=name,
                normalizer=normalize_name,
            )
            if item:
                candidates["lessor_name"].append(item)
                lessor_values.add(str(item.normalized_value))

    if not candidates["lessee_name"]:
        for line, name in unique_names:
            if normalize_name(name) in lessor_values:
                continue
            item = _text_candidate(
                document_id=document_id,
                line=line,
                raw_value=name,
                normalizer=normalize_name,
            )
            if item:
                candidates["lessee_name"].append(item)
                break

    if not candidates["lessee_name"]:
        fallback_lessee = _role_nearby_name(
            lines,
            role_marker="임차인",
            excluded_names=lessor_values,
        )
        if fallback_lessee is not None:
            line, name = fallback_lessee
            item = _text_candidate(
                document_id=document_id,
                line=line,
                raw_value=name,
                normalizer=normalize_name,
            )
            if item:
                candidates["lessee_name"].append(item)


def _add_address_candidate(
    *,
    document_id: str,
    lines: list[_Line],
    candidates: dict[str, list[FieldCandidate]],
) -> None:
    section_end = next(
        (index for index, item in enumerate(lines) if "제1조" in item.compact),
        min(len(lines), 30),
    )
    early_lines = lines[: max(section_end, 12)]
    for line in early_lines:
        match = re.search(
            r"(?:소재지|목적물(?:소재지)?|임대차목적물|주소)[:：]?(.+)$",
            line.compact,
        )
        if match:
            item = _text_candidate(
                document_id=document_id,
                line=line,
                raw_value=match.group(1),
                normalizer=normalize_whitespace,
            )
            if item:
                candidates["property_address"].append(item)
                return

    for line in early_lines:
        if not any(marker in line.compact for marker in _REGION_MARKERS):
            continue
        if not re.search(r"(?:제)?\d{1,5}호", line.compact):
            continue
        raw = re.sub(
            r"^.*?(?=(?:서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|울산광역시|세종특별자치시|경기도|강원특별자치도|충청북도|충청남도|전북특별자치도|전라남도|경상북도|경상남도|제주특별자치도))",
            "",
            line.text,
        )
        item = _text_candidate(
            document_id=document_id,
            line=line,
            raw_value=raw,
            normalizer=normalize_whitespace,
        )
        if item:
            candidates["property_address"].append(item)
            return


def _add_amount_candidates(
    *,
    document_id: str,
    lines: list[_Line],
    candidates: dict[str, list[FieldCandidate]],
) -> None:
    for line in lines:
        for key, pattern in _AMOUNT_LABEL_PATTERNS.items():
            match = pattern.search(line.compact)
            if not match:
                continue
            item = _text_candidate(
                document_id=document_id,
                line=line,
                raw_value=match.group(1),
                normalizer=normalize_amount,
            )
            if item:
                candidates[key].append(item)

    start = next(
        (index for index, item in enumerate(lines) if "제1조" in item.compact),
        0,
    )
    end = next(
        (
            index
            for index, item in enumerate(lines[start + 1 :], start + 1)
            if "제2조" in item.compact
        ),
        min(len(lines), start + 20),
    )
    ordered: list[tuple[_Line, str, int]] = []
    seen_amounts: set[int] = set()
    for line in lines[start:end]:
        for match in _MONEY_TOKEN.finditer(line.text):
            value = normalize_amount(match.group(1))
            if value is None or value < 100_000 or value in seen_amounts:
                continue
            seen_amounts.add(value)
            ordered.append((line, match.group(1), value))

    existing = {
        key: {int(item.normalized_value) for item in values}
        for key, values in candidates.items()
        if key in _AMOUNT_LABEL_PATTERNS
    }
    if len(ordered) >= 3:
        deposit, contract, balance = ordered[:3]
        if deposit[2] == contract[2] + balance[2]:
            for key, current in (
                ("deposit_amount", deposit),
                ("contract_payment", contract),
                ("balance_payment", balance),
            ):
                if existing.get(key):
                    continue
                line, raw, _ = current
                item = _text_candidate(
                    document_id=document_id,
                    line=line,
                    raw_value=raw,
                    normalizer=normalize_amount,
                )
                if item:
                    candidates[key].append(item)


def _dates_from_line(line: _Line) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for match in _DATE_TOKEN.finditer(line.text):
        normalized = normalize_date(match.group(0))
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append((match.group(0), normalized))

    if result:
        return result

    # 한글 날짜 구분자가 숫자로 인식된 실제 OCR 형태를 제한적으로 복원한다.
    # 예: 2024년11월28일 -> 20246118282 (년=6, 월=8, 일=2)
    compact = compact_ocr_text(line.text)
    for match in _OCR_COMPACT_DATE_TOKEN.finditer(compact):
        raw = (
            f"{match.group('year')}-{int(match.group('month')):02d}-"
            f"{int(match.group('day')):02d}"
        )
        normalized = normalize_date(raw)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append((raw, normalized))
    return result


def _add_date_candidates(
    *,
    document_id: str,
    lines: list[_Line],
    candidates: dict[str, list[FieldCandidate]],
) -> None:
    for line in lines:
        dates = _dates_from_line(line)
        if not dates:
            continue
        compact = line.compact

        handover_context = (
            "존속기간" in compact
            or "임차인에게인도" in compact
            or "인도하며" in compact
            or "입주일" in compact
        )
        if handover_context:
            first_raw, _ = dates[0]
            move_in = _text_candidate(
                document_id=document_id,
                line=line,
                raw_value=first_raw,
                normalizer=normalize_date,
            )
            if move_in:
                candidates["move_in_date"].append(move_in)
                candidates["contract_start_date"].append(move_in)
            if len(dates) >= 2:
                end = _text_candidate(
                    document_id=document_id,
                    line=line,
                    raw_value=dates[-1][0],
                    normalizer=normalize_date,
                )
                if end:
                    candidates["contract_end_date"].append(end)

        if "계약기간" in compact or "임대차기간" in compact:
            if len(dates) >= 2:
                start_raw, _ = dates[0]
                end_raw, _ = dates[1]
                start = _text_candidate(
                    document_id=document_id,
                    line=line,
                    raw_value=start_raw,
                    normalizer=normalize_date,
                )
                end = _text_candidate(
                    document_id=document_id,
                    line=line,
                    raw_value=end_raw,
                    normalizer=normalize_date,
                )
                if start:
                    candidates["contract_start_date"].append(start)
                if end:
                    candidates["contract_end_date"].append(end)
            elif "인도일로부터" in compact or "개월" in compact:
                end = _text_candidate(
                    document_id=document_id,
                    line=line,
                    raw_value=dates[-1][0],
                    normalizer=normalize_date,
                )
                if end:
                    candidates["contract_end_date"].append(end)

        if (
            "인도" in compact
            and "인도일로부터" not in compact
            and ("까지" in compact or "입주" in compact or "존속기간" in compact)
        ):
            move_in = _text_candidate(
                document_id=document_id,
                line=line,
                raw_value=dates[0][0],
                normalizer=normalize_date,
            )
            if move_in:
                candidates["move_in_date"].append(move_in)
                if not candidates["contract_start_date"]:
                    candidates["contract_start_date"].append(move_in)

        if "계약일" in compact or "계약체결일" in compact:
            contract_date = _text_candidate(
                document_id=document_id,
                line=line,
                raw_value=dates[0][0],
                normalizer=normalize_date,
            )
            if contract_date:
                candidates["contract_date"].append(contract_date)
        elif (
            any(marker in compact for marker in ("본계약을증명", "기명날인", "서명또는"))
            and dates
        ):
            contract_date = _text_candidate(
                document_id=document_id,
                line=line,
                raw_value=dates[-1][0],
                normalizer=normalize_date,
            )
            if contract_date:
                candidates["contract_date"].append(contract_date)

    if not candidates["contract_date"]:
        for index in range(len(lines) - 1, -1, -1):
            dates = _dates_from_line(lines[index])
            if not dates:
                continue
            nearby = "".join(
                item.compact
                for item in lines[max(0, index - 8) : index + 1]
            )
            attestation_context = (
                "본계약을증명" in nearby
                or "계약을증명" in nearby
                or "기명날인" in nearby
                or ("증명" in nearby and "서명" in nearby)
            )
            if not attestation_context:
                continue
            contract_date = _text_candidate(
                document_id=document_id,
                line=lines[index],
                raw_value=dates[-1][0],
                normalizer=normalize_date,
            )
            if contract_date:
                candidates["contract_date"].append(contract_date)
                break

    if not candidates["contract_start_date"] and candidates["move_in_date"]:
        candidates["contract_start_date"].append(candidates["move_in_date"][0])



def analyze_lease_contract(
    *,
    document: UploadedDocument,
    extraction: DocumentExtractionResult,
) -> LeaseAnalysisResult:
    started_at = utc_now()
    lines = _page_lines(extraction)
    candidates: dict[str, list[FieldCandidate]] = {
        key: [] for key in FIELD_LABELS
    }

    _add_name_candidates(
        document_id=document.document_id,
        lines=lines,
        candidates=candidates,
    )
    _add_address_candidate(
        document_id=document.document_id,
        lines=lines,
        candidates=candidates,
    )
    _add_amount_candidates(
        document_id=document.document_id,
        lines=lines,
        candidates=candidates,
    )
    _add_date_candidates(
        document_id=document.document_id,
        lines=lines,
        candidates=candidates,
    )

    for line in lines:
        compact = line.compact
        if "오피스텔" in compact:
            item = _text_candidate(
                document_id=document.document_id,
                line=line,
                raw_value="오피스텔",
                normalizer=normalize_whitespace,
            )
            if item:
                candidates["housing_type"].append(item)
                break
        for key, pattern in _SIGNATURE_PATTERNS.items():
            if pattern.search(compact):
                item = _text_candidate(
                    document_id=document.document_id,
                    line=line,
                    raw_value="text_marker_present",
                    normalizer=lambda value: True,
                )
                if item:
                    candidates[key].append(item)

    clauses = _special_clauses(lines=lines)
    for clause in clauses:
        page = next(
            current
            for current in extraction.pages
            if current.page_number == clause.page_number
        )
        item = candidate(
            document_id=document.document_id,
            page=page,
            raw_value=clause.text,
            evidence_text=clause.text,
            normalizer=normalize_whitespace,
        )
        if item:
            candidates["special_clause_text"].append(item)

    fields = {
        key: build_field(
            key=key,
            label=FIELD_LABELS[key],
            candidates=items,
            multi_value=(key == "special_clause_text"),
        )
        for key, items in candidates.items()
    }

    warnings: list[str] = []
    if not lines:
        warnings.append("분석할 수 있는 성공 페이지 텍스트가 없습니다.")
    if fields["lessor_name"].status == AnalysisValueStatus.UNKNOWN:
        warnings.append("임대인 이름을 확인하지 못했습니다.")
    if fields["lessee_name"].status == AnalysisValueStatus.UNKNOWN:
        warnings.append("임차인 이름을 확인하지 못했습니다.")
    if fields["property_address"].status == AnalysisValueStatus.UNKNOWN:
        warnings.append("임대차 목적물 주소를 확인하지 못했습니다.")
    if fields["deposit_amount"].status == AnalysisValueStatus.UNKNOWN:
        warnings.append("보증금 값을 확인하지 못했습니다.")

    return LeaseAnalysisResult(
        analysis_version=ANALYSIS_VERSION,
        document_id=document.document_id,
        conversation_id=document.conversation_id,
        source_sha256=document.sha256,
        source_extraction_version=extraction.extraction_version,
        fields=fields,
        special_clauses=clauses,
        warnings=warnings,
        started_at=started_at,
        completed_at=utc_now(),
    )
