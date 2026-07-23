"""계약서·등기부 필드 비교를 위한 이름·주소·금액·날짜 정규화."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

_KOREAN_DIGITS = {
    "영": 0,
    "공": 0,
    "일": 1,
    "이": 2,
    "삼": 3,
    "사": 4,
    "오": 5,
    "육": 6,
    "칠": 7,
    "팔": 8,
    "구": 9,
}
_SMALL_UNITS = {"십": 10, "백": 100, "천": 1000}
_LARGE_UNITS = {"만": 10_000, "억": 100_000_000, "조": 1_000_000_000_000}
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


def normalize_whitespace(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    return " ".join(normalized.replace("\u00a0", " ").split()).strip()


def compact_ocr_text(value: str) -> str:
    """OCR이 한글 음절 사이에 넣은 공백과 표 구분 기호를 비교용으로 제거한다."""

    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = normalized.replace("\u00a0", " ")
    return re.sub(r"[\s|｜¦]+", "", normalized).strip()


def normalize_name(value: str) -> str:
    normalized = normalize_whitespace(value).lower()
    normalized = re.sub(
        r"(?:임대인|임차인|소유자|공유자|현재|성명|성명란)",
        "",
        normalized,
    )
    return re.sub(r"[^0-9a-z가-힣]", "", normalized)


def repair_address_ocr(value: str) -> str:
    """주소 줄에서 반복적으로 나타나는 OCR 오인식을 비교용으로만 보정한다.

    원문을 바꾸는 용도가 아니라 주소 구성요소를 안전하게 비교하기 위한 전처리다.
    """

    compact = compact_ocr_text(value)
    corrections = {
        "제2충": "제2층",
        "제3충": "제3층",
        "제4충": "제4층",
        "제5충": "제5층",
        "제6충": "제6층",
        "제7충": "제7층",
        "제8충": "제8층",
        "제9충": "제9층",
        "제10충": "제10층",
    }
    for source, target in corrections.items():
        compact = compact.replace(source, target)

    # 실제 문서에서 "제2층"이 A2S, AS처럼 인식된 경우를 호수 앞 문맥에서만 보정한다.
    compact = re.sub(
        r"(?:A2S|A2층|A2충|AS)(?=제?\d{1,5}호)",
        "제2층",
        compact,
        flags=re.IGNORECASE,
    )

    # "5-75 외 6필지"가 "5-759] 0필지"처럼 붙은 경우 기본 지번만 복원한다.
    compact = re.sub(
        r"(\d{1,4}-\d{1,3}?)(?:9\]|\])\d{1,2}필지",
        r"\1",
        compact,
    )
    compact = re.sub(r"(?:외|의)\d+필지", "", compact)
    region_positions = [
        compact.find(marker) for marker in _REGION_MARKERS if marker in compact
    ]
    if region_positions:
        compact = compact[min(region_positions) :]
    return compact


def normalize_address(value: str) -> str:
    normalized = repair_address_ocr(value).lower()
    replacements = {
        "서울특별시": "서울",
        "부산광역시": "부산",
        "대구광역시": "대구",
        "인천광역시": "인천",
        "광주광역시": "광주",
        "대전광역시": "대전",
        "울산광역시": "울산",
        "세종특별자치시": "세종",
        "제주특별자치도": "제주",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(r"제(?=\d)", "", normalized)
    normalized = normalized.replace("번지", "")
    normalized = re.sub(r"(?:외|의)\d+필지", "", normalized)
    return re.sub(r"[^0-9a-z가-힣]", "", normalized)


def extract_address_components(value: str) -> dict[str, str]:
    """주소 전체 문자열이 조금 깨져도 핵심 지번·동·호수 단위를 비교한다."""

    compact = repair_address_ocr(value)
    components: dict[str, str] = {}

    location_tail = compact
    for marker in _REGION_MARKERS:
        if marker in compact:
            location_tail = compact.split(marker, 1)[1]
            break

    district_match = re.search(r"([가-힣]{1,6}(?:구|군))", location_tail)
    if district_match:
        components["district"] = district_match.group(1)
        after_district = location_tail[district_match.end() :]
    else:
        after_district = location_tail

    neighborhood_match = re.search(
        r"([가-힣]{1,8}(?:동|읍|면|리))",
        after_district,
    )
    if neighborhood_match:
        components["neighborhood"] = neighborhood_match.group(1)

    road_match = re.search(
        r"([가-힣A-Za-z0-9]{1,20}(?:로|길)\d{1,5})",
        after_district,
    )
    if road_match:
        components["road"] = road_match.group(1)

    patterns = {
        "lot": r"(?<!\d)(\d{1,4}-\d{1,4})(?!\d)",
        "floor": r"(?:제)?(\d{1,3})[층충]",
        "unit": r"(?:제)?(\d{1,5})호",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, compact)
        if match:
            components[key] = match.group(1)

    building_patterns = (
        r"([가-힣A-Za-z][가-힣A-Za-z0-9]*(?:시티|아파트|오피스텔|빌라)\d*)",
        r"([가-힣A-Za-z][가-힣A-Za-z0-9]*(?:타워|센터|캐슬|하우스)\d*)",
    )
    for pattern in building_patterns:
        match = re.search(pattern, compact)
        if match:
            components["building"] = match.group(1)
            break
    return components


def address_signal_score(value: str) -> int:
    """등기부 후보 줄이 실제 목적물 주소에 가까운 정도를 계산한다."""

    compact = repair_address_ocr(value)
    components = extract_address_components(value)
    score = len(components) * 2
    if any(marker in compact for marker in _REGION_MARKERS):
        score += 3
    if "집합건물" in compact:
        score += 1
    if "소재지번" in compact or "등기원인" in compact:
        score -= 4
    if len(compact) < 12:
        score -= 8
    return score


def compare_addresses_safely(
    left: str,
    right: str,
) -> tuple[bool | None, dict[str, Any]]:
    """완전 일치, 핵심 구성요소 일치, 충돌, 비교 부족을 구분한다.

    OCR 지번 한 글자 오류만으로 실제 같은 목적물을 불일치로 단정하지 않는다.
    구·동·호수 같은 핵심 값이 충돌할 때만 불일치를 확정한다.
    """

    normalized_left = normalize_address(left)
    normalized_right = normalize_address(right)
    left_components = extract_address_components(left)
    right_components = extract_address_components(right)
    details: dict[str, Any] = {
        "normalized_left": normalized_left,
        "normalized_right": normalized_right,
        "left_components": left_components,
        "right_components": right_components,
        "matched_components": [],
        "conflicting_components": [],
        "soft_conflicting_components": [],
    }

    if not normalized_left or not normalized_right:
        return None, details
    if (
        normalized_left == normalized_right
        or normalized_left in normalized_right
        or normalized_right in normalized_left
    ):
        return True, details

    hard_keys = ("district", "unit")
    soft_keys = ("neighborhood", "road", "lot", "floor", "building")
    for key in (*hard_keys, *soft_keys):
        left_value = left_components.get(key)
        right_value = right_components.get(key)
        if not left_value or not right_value:
            continue
        if left_value == right_value:
            details["matched_components"].append(key)
        elif key in hard_keys:
            details["conflicting_components"].append(key)
        else:
            details["soft_conflicting_components"].append(key)

    if details["conflicting_components"]:
        return False, details

    matched = set(details["matched_components"])
    if {"district", "unit"}.issubset(matched):
        if matched.intersection({"neighborhood", "road", "lot", "floor", "building"}):
            return True, details
    if {"district", "road", "unit"}.issubset(matched):
        return True, details
    if {"district", "neighborhood", "lot", "unit"}.issubset(matched):
        return True, details
    if {"district", "neighborhood", "building", "unit"}.issubset(matched):
        return True, details
    if len(matched) >= 4 and "unit" in matched:
        return True, details
    return None, details


def korean_number_to_int(value: str) -> int | None:
    text = re.sub(r"[^영공일이삼사오육칠팔구십백천만억조]", "", value)
    if not text:
        return None
    if not any(character in text for character in [*_SMALL_UNITS, *_LARGE_UNITS]):
        return None

    total = 0
    section = 0
    number = 0
    seen = False
    for character in text:
        if character in _KOREAN_DIGITS:
            number = _KOREAN_DIGITS[character]
            seen = True
            continue
        if character in _SMALL_UNITS:
            unit = _SMALL_UNITS[character]
            section += (number or 1) * unit
            number = 0
            seen = True
            continue
        if character in _LARGE_UNITS:
            unit = _LARGE_UNITS[character]
            section += number
            total += (section or 1) * unit
            section = 0
            number = 0
            seen = True
    return total + section + number if seen else None


def normalize_amount(value: str) -> int | None:
    normalized = unicodedata.normalize("NFKC", value or "")
    digit_groups = re.findall(r"\d[\d, ]*", normalized)
    if digit_groups:
        digits = re.sub(r"\D", "", max(digit_groups, key=len))
        if digits:
            return int(digits)
    return korean_number_to_int(normalized)


def normalize_date(value: str) -> str | None:
    normalized = unicodedata.normalize("NFKC", value or "")
    match = re.search(
        r"(?P<year>20\d{2}|19\d{2})\s*[년./-]\s*"
        r"(?P<month>\d{1,2})\s*[월./-]\s*"
        r"(?P<day>\d{1,2})\s*일?",
        normalized,
    )
    if not match:
        compact = re.search(
            r"\b(20\d{2})(\d{2})(\d{2})\b|\b(19\d{2})(\d{2})(\d{2})\b",
            normalized,
        )
        if not compact:
            return None
        groups = [item for item in compact.groups() if item is not None]
        year, month, day = map(int, groups)
    else:
        year = int(match.group("year"))
        month = int(match.group("month"))
        day = int(match.group("day"))
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def normalize_text_value(value: str) -> str:
    return normalize_whitespace(value).lower()


def normalize_string_list(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = normalize_name(value)
        if normalized and normalized not in result:
            result.append(normalized)
    return sorted(result)
