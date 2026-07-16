"""페이지 추출 방식과 값 형식을 이용해 필드 상태를 결정한다."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from app.documents.analysis.models import (
    AnalysisEvidence,
    AnalysisValueStatus,
    AnalyzedField,
)
from app.documents.extraction_models import ExtractionMethod, PageExtractionResult


Normalizer = Callable[[str], Any | None]


@dataclass(frozen=True)
class FieldCandidate:
    raw_value: str
    normalized_value: Any
    evidence: AnalysisEvidence
    confidence: float
    warnings: tuple[str, ...] = ()


def page_confidence(page: PageExtractionResult) -> float:
    if page.extraction_method == ExtractionMethod.DIRECT_TEXT:
        return float(page.direct_text_quality_score or 1.0)
    if page.extraction_method == ExtractionMethod.OCR:
        return float(page.ocr_confidence or 0.0) / 100.0
    return 0.0


def make_evidence(
    *,
    document_id: str,
    page: PageExtractionResult,
    text: str,
) -> AnalysisEvidence:
    return AnalysisEvidence(
        document_id=document_id,
        page_number=page.page_number,
        text=text.strip(),
        extraction_method=page.extraction_method.value,
        extraction_confidence=page_confidence(page),
    )


def suspicious_ocr_value(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return True
    if "�" in compact:
        return True
    if re.search(r"\d[OoIl|]\d|[OoIl|]\d{2,}", compact):
        return True
    return False


def candidate(
    *,
    document_id: str,
    page: PageExtractionResult,
    raw_value: str,
    evidence_text: str,
    normalizer: Normalizer,
) -> FieldCandidate | None:
    normalized = normalizer(raw_value)
    if normalized is None or normalized == "" or normalized == []:
        return None
    confidence = page_confidence(page)
    warnings: list[str] = []
    if page.extraction_method == ExtractionMethod.OCR:
        if confidence < 0.85:
            warnings.append("OCR 평균 신뢰도가 85% 미만입니다.")
        if suspicious_ocr_value(raw_value):
            warnings.append("OCR 결과에 숫자와 혼동될 수 있는 문자가 있습니다.")
    return FieldCandidate(
        raw_value=raw_value.strip(),
        normalized_value=normalized,
        evidence=make_evidence(
            document_id=document_id,
            page=page,
            text=evidence_text,
        ),
        confidence=confidence,
        warnings=tuple(warnings),
    )


def _comparable(value: Any) -> Any:
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((str(key), str(item)) for key, item in value.items()))
    return value


def build_field(
    *,
    key: str,
    label: str,
    candidates: list[FieldCandidate],
    multi_value: bool = False,
) -> AnalyzedField:
    if not candidates:
        return AnalyzedField(key=key, label=label)

    unique: list[FieldCandidate] = []
    seen: set[Any] = set()
    for item in candidates:
        comparable = _comparable(item.normalized_value)
        if comparable in seen:
            continue
        seen.add(comparable)
        unique.append(item)

    warnings = sorted({warning for item in candidates for warning in item.warnings})
    evidences = [item.evidence for item in candidates]
    raw_values = [item.raw_value for item in candidates]
    confidence = min(item.confidence for item in candidates)

    if multi_value:
        values: list[Any] = []
        for item in unique:
            current = item.normalized_value
            if isinstance(current, list):
                values.extend(current)
            else:
                values.append(current)
        deduplicated: list[Any] = []
        for value in values:
            if _comparable(value) not in {_comparable(item) for item in deduplicated}:
                deduplicated.append(value)
        status = (
            AnalysisValueStatus.CONFIRMED
            if confidence >= 0.85 and not warnings
            else AnalysisValueStatus.UNCERTAIN
        )
        return AnalyzedField(
            key=key,
            label=label,
            status=status,
            value=deduplicated,
            raw_values=raw_values,
            confidence=confidence,
            evidences=evidences,
            warnings=warnings,
        )

    if len(unique) > 1:
        return AnalyzedField(
            key=key,
            label=label,
            status=AnalysisValueStatus.CONFLICT,
            value=[item.normalized_value for item in unique],
            raw_values=raw_values,
            confidence=confidence,
            evidences=evidences,
            warnings=["문서 안에서 서로 다른 값이 확인됐습니다.", *warnings],
        )

    selected = unique[0]
    status = (
        AnalysisValueStatus.CONFIRMED
        if selected.confidence >= 0.85 and not selected.warnings
        else AnalysisValueStatus.UNCERTAIN
    )
    return AnalyzedField(
        key=key,
        label=label,
        status=status,
        value=selected.normalized_value,
        raw_values=raw_values,
        confidence=selected.confidence,
        evidences=evidences,
        warnings=warnings,
    )
