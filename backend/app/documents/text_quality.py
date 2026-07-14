"""PDF 텍스트 레이어의 직접 추출 결과가 사용 가능한지 평가한다."""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.documents.text_metrics import normalize_text


@dataclass(frozen=True, slots=True)
class DirectTextQualityResult:
    usable: bool
    score: float
    compact_character_count: int
    meaningful_character_ratio: float
    replacement_character_ratio: float
    control_character_ratio: float
    repeated_symbol_ratio: float
    reasons: tuple[str, ...]


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_direct_text_quality(
    text: str,
    *,
    minimum_compact_characters: int = 20,
    minimum_meaningful_ratio: float = 0.45,
    maximum_replacement_ratio: float = 0.05,
    maximum_control_ratio: float = 0.01,
    maximum_repeated_symbol_ratio: float = 0.35,
    minimum_score: float = 0.60,
) -> DirectTextQualityResult:
    """직접 추출 텍스트를 글자 수와 깨짐 비율로 평가한다.

    이 점수는 법률 내용의 정확성을 판단하지 않는다.
    PDF 내부 문자열이 비어 있거나 깨져 OCR 전환이 필요한지를 판단한다.
    """

    normalized = normalize_text(text, keep_line_breaks=True)
    compact = re.sub(r"\s+", "", normalized)
    total = len(compact)

    meaningful = sum(
        1
        for character in compact
        if character.isalnum()
        or "가" <= character <= "힣"
        or "ㄱ" <= character <= "ㅎ"
        or "ㅏ" <= character <= "ㅣ"
    )
    replacement = compact.count("�") + compact.count("\ufffd")
    controls = sum(
        1
        for character in normalized
        if ord(character) < 32 and character not in {"\n", "\t"}
    )
    repeated_symbols = len(
        re.findall(r"([^\w\s가-힣])\1{2,}", compact)
    )

    meaningful_ratio = _ratio(meaningful, total)
    replacement_ratio = _ratio(replacement, total)
    control_ratio = _ratio(controls, max(len(normalized), 1))
    repeated_symbol_ratio = _ratio(repeated_symbols * 3, max(total, 1))

    score = 1.0
    reasons: list[str] = []

    if total < minimum_compact_characters:
        score -= 0.55
        reasons.append(
            f"공백 제외 글자 수가 {total}자로 최소 {minimum_compact_characters}자보다 적습니다."
        )
    if meaningful_ratio < minimum_meaningful_ratio:
        score -= 0.35
        reasons.append(
            "한글·영문·숫자 비율이 낮아 텍스트 레이어가 깨졌을 가능성이 있습니다."
        )
    if replacement_ratio > maximum_replacement_ratio:
        score -= 0.45
        reasons.append("대체 문자 비율이 높습니다.")
    if control_ratio > maximum_control_ratio:
        score -= 0.25
        reasons.append("제어 문자 비율이 높습니다.")
    if repeated_symbol_ratio > maximum_repeated_symbol_ratio:
        score -= 0.25
        reasons.append("같은 기호가 과도하게 반복됩니다.")

    score = min(1.0, max(0.0, score))
    usable = (
        total >= minimum_compact_characters
        and meaningful_ratio >= minimum_meaningful_ratio
        and replacement_ratio <= maximum_replacement_ratio
        and control_ratio <= maximum_control_ratio
        and repeated_symbol_ratio <= maximum_repeated_symbol_ratio
        and score >= minimum_score
    )

    if usable:
        reasons.append("PDF 텍스트 레이어를 직접 사용할 수 있습니다.")

    return DirectTextQualityResult(
        usable=usable,
        score=score,
        compact_character_count=total,
        meaningful_character_ratio=meaningful_ratio,
        replacement_character_ratio=replacement_ratio,
        control_character_ratio=control_ratio,
        repeated_symbol_ratio=repeated_symbol_ratio,
        reasons=tuple(reasons),
    )
