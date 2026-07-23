"""공통 문서 업로드와 텍스트 추출에서 사용하는 문서 모델."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentType(str, Enum):
    LEASE_CONTRACT = "lease_contract"
    REGISTRY = "registry"
    TRANSFER_RECEIPT = "transfer_receipt"
    DELEGATION = "delegation"
    OTHER = "other"


class DocumentFormat(str, Enum):
    PDF = "pdf"


class DocumentProcessingStatus(str, Enum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class DocumentAnalysisStatus(str, Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class UploadedDocument(BaseModel):
    """업로드 원본과 이후 추출 결과를 연결하는 문서 메타데이터."""

    document_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    document_type: DocumentType
    original_filename: str = Field(min_length=1, max_length=512)
    safe_filename: str = Field(min_length=1, max_length=180)
    stored_filename: str = Field(min_length=1)
    stored_path: str = Field(min_length=1)
    detected_format: DocumentFormat
    content_type: str = Field(min_length=1)
    declared_content_type: str | None = None
    size_bytes: int = Field(gt=0)
    sha256: str = Field(min_length=64, max_length=64)
    processing_status: DocumentProcessingStatus = DocumentProcessingStatus.UPLOADED
    extraction_method: str | None = None
    extraction_version: str | None = None
    page_count: int | None = Field(default=None, ge=0)
    successful_page_count: int | None = Field(default=None, ge=0)
    failed_page_count: int | None = Field(default=None, ge=0)
    direct_text_page_count: int | None = Field(default=None, ge=0)
    ocr_page_count: int | None = Field(default=None, ge=0)
    text_character_count: int | None = Field(default=None, ge=0)
    average_ocr_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=100.0,
    )
    average_direct_text_quality: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )
    extraction_total_seconds: float | None = Field(default=None, ge=0.0)
    extraction_result_path: str | None = None
    extracted_text_path: str | None = None
    extraction_warnings: list[str] = Field(default_factory=list)
    extraction_error: str | None = None
    extraction_started_at: datetime | None = None
    extraction_completed_at: datetime | None = None
    analysis_status: DocumentAnalysisStatus = DocumentAnalysisStatus.PENDING
    analysis_version: str | None = None
    analysis_result_path: str | None = None
    analysis_warnings: list[str] = Field(default_factory=list)
    analysis_error: str | None = None
    analysis_started_at: datetime | None = None
    analysis_completed_at: datetime | None = None
    is_duplicate: bool = False
    duplicate_of: str | None = None
    uploaded_at: datetime = Field(default_factory=utc_now)

    @field_validator(
        "stored_path",
        "extraction_result_path",
        "extracted_text_path",
        "analysis_result_path",
    )
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\\", "/").strip()
        if not normalized:
            raise ValueError("문서 경로는 빈 문자열일 수 없습니다.")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("문서 경로는 안전한 상대 경로여야 합니다.")
        return normalized

    def as_conversation_reference(self) -> "UploadedDocument":
        """중복 재업로드 표시를 제거한 상태 저장용 복사본을 반환한다."""

        return self.model_copy(
            update={
                "is_duplicate": False,
                "duplicate_of": None,
            }
        )


class DocumentUploadResult(BaseModel):
    document: UploadedDocument
    conversation_document_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    state: Any | None = None
