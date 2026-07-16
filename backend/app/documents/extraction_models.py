"""페이지별 직접 추출·OCR 결과와 문서 전체 추출 결과 모델."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.documents.models import (
    DocumentProcessingStatus,
    UploadedDocument,
    utc_now,
)


EXTRACTION_VERSION = "document-extraction-v5-lease-registry-local-ocr"
ALL_OCR_BENCHMARK_VERSION = "document-ocr-v1-all-pages-benchmark"


class ExtractionMethod(str, Enum):
    DIRECT_TEXT = "direct_text"
    OCR = "ocr"
    MIXED = "mixed"
    NONE = "none"


class PDFExtractionStrategy(str, Enum):
    DIRECT_TEXT_FIRST = "direct_text_first"
    ALL_OCR = "all_ocr"


class PageExtractionStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class PageExtractionResult(BaseModel):
    page_number: int = Field(ge=1)
    status: PageExtractionStatus
    extraction_method: ExtractionMethod
    text: str = ""
    direct_text: str = ""
    ocr_text: str = ""
    character_count: int = Field(default=0, ge=0)
    direct_text_character_count: int = Field(default=0, ge=0)
    direct_text_quality_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    direct_text_quality_reasons: list[str] = Field(default_factory=list)
    fallback_to_ocr: bool = False
    ocr_confidence: float | None = Field(default=None, ge=0.0, le=100.0)
    direct_text_seconds: float = Field(default=0.0, ge=0.0)
    render_seconds: float = Field(default=0.0, ge=0.0)
    ocr_seconds: float = Field(default=0.0, ge=0.0)
    postprocess_seconds: float = Field(default=0.0, ge=0.0)
    total_seconds: float = Field(default=0.0, ge=0.0)
    image_width: int | None = Field(default=None, ge=1)
    image_height: int | None = Field(default=None, ge=1)
    warnings: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class DocumentExtractionResult(BaseModel):
    extraction_version: str = EXTRACTION_VERSION
    document_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    source_sha256: str = Field(min_length=64, max_length=64)
    processing_status: DocumentProcessingStatus
    extraction_method: ExtractionMethod
    pdf_strategy: PDFExtractionStrategy = PDFExtractionStrategy.DIRECT_TEXT_FIRST
    detected_format: str
    page_count: int = Field(ge=0)
    successful_page_count: int = Field(ge=0)
    failed_page_count: int = Field(ge=0)
    direct_text_page_count: int = Field(default=0, ge=0)
    ocr_page_count: int = Field(default=0, ge=0)
    text_character_count: int = Field(ge=0)
    average_ocr_confidence: float | None = Field(default=None, ge=0.0, le=100.0)
    average_direct_text_quality: float | None = Field(default=None, ge=0.0, le=1.0)
    open_seconds: float = Field(default=0.0, ge=0.0)
    direct_text_seconds: float = Field(default=0.0, ge=0.0)
    render_seconds: float = Field(default=0.0, ge=0.0)
    ocr_seconds: float = Field(default=0.0, ge=0.0)
    total_seconds: float = Field(default=0.0, ge=0.0)
    render_dpi: int = Field(ge=72)
    ocr_language: str = Field(min_length=1)
    ocr_config: str = Field(min_length=1)
    combined_text: str = ""
    pages: list[PageExtractionResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    extraction_result_path: str | None = None
    extracted_text_path: str | None = None
    reused: bool = False
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    @field_validator("extraction_result_path", "extracted_text_path")
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\\", "/").strip()
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("추출 결과 경로는 안전한 상대 경로여야 합니다.")
        return normalized


class DocumentExtractionResponse(BaseModel):
    document: UploadedDocument
    extraction: DocumentExtractionResult
    state: Any | None = None


class TesseractEnvironment(BaseModel):
    available: bool
    version: str | None = None
    executable: str | None = None
    installed_languages: list[str] = Field(default_factory=list)
    required_languages: list[str] = Field(default_factory=lambda: ["kor", "eng"])
    missing_languages: list[str] = Field(default_factory=list)
    error: str | None = None
