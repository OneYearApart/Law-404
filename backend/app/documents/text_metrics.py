"""OCR 결과를 비교할 때 사용하는 텍스트 정규화와 문자 오류율 계산."""

from __future__ import annotations

import re
import unicodedata


def normalize_text(text: str, *, keep_line_breaks: bool = False) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    if keep_line_breaks:
        normalized = re.sub(r"[ \t]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_compact(text: str) -> str:
    """공백과 일반 구분 기호를 제거해 숫자·주소 핵심값 비교에 사용한다."""

    normalized = normalize_text(text).lower()
    return re.sub(r"[\s,.:;()\[\]{}\-_]+", "", normalized)


def levenshtein_distance(reference: str, candidate: str) -> int:
    if reference == candidate:
        return 0
    if not reference:
        return len(candidate)
    if not candidate:
        return len(reference)

    previous = list(range(len(candidate) + 1))
    for row_index, ref_char in enumerate(reference, start=1):
        current = [row_index]
        for column_index, cand_char in enumerate(candidate, start=1):
            insertion = current[column_index - 1] + 1
            deletion = previous[column_index] + 1
            substitution = previous[column_index - 1] + (
                0 if ref_char == cand_char else 1
            )
            current.append(min(insertion, deletion, substitution))
        previous = current
    return previous[-1]


def character_error_rate(
    reference: str,
    candidate: str,
    *,
    normalize: bool = True,
) -> float:
    expected = normalize_text(reference) if normalize else (reference or "")
    actual = normalize_text(candidate) if normalize else (candidate or "")
    if not expected:
        return 0.0 if not actual else 1.0
    return levenshtein_distance(expected, actual) / len(expected)


def contains_expected_value(text: str, expected: str) -> bool:
    return normalize_compact(expected) in normalize_compact(text)
