"""계약서·등기부 필드 분석과 문서 비교 결과 모델."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.documents.models import utc_now

ANALYSIS_VERSION = "document-analysis-v11-generic-document-summary"
COMPARISON_VERSION = "document-comparison-v7-lease-registry-only"


class AnalysisValueStatus(str, Enum):
    UNKNOWN = "unknown"
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"
    CONFLICT = "conflict"


class AnalysisEvidence(BaseModel):
    document_id: str
    page_number: int = Field(ge=1)
    text: str = Field(min_length=1)
    extraction_method: str
    extraction_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class AnalyzedField(BaseModel):
    key: str
    label: str
    status: AnalysisValueStatus = AnalysisValueStatus.UNKNOWN
    value: Any | None = None
    raw_values: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidences: list[AnalysisEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def is_available(self) -> bool:
        return self.status in {
            AnalysisValueStatus.CONFIRMED,
            AnalysisValueStatus.UNCERTAIN,
            AnalysisValueStatus.CONFLICT,
        }


class SpecialClause(BaseModel):
    text: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    categories: list[str] = Field(default_factory=list)
    extraction_method: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: AnalysisValueStatus = AnalysisValueStatus.CONFIRMED


class RegistryRight(BaseModel):
    right_type: str
    holder: str | None = None
    amount: int | None = Field(default=None, ge=0)
    registration_date: str | None = None
    active: bool | None = None
    cancellation_status: str | None = None
    raw_text: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    extraction_method: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class LeaseAnalysisResult(BaseModel):
    analysis_version: str = ANALYSIS_VERSION
    document_id: str
    source_document_ids: list[str] = Field(default_factory=list)
    conversation_id: str
    source_sha256: str = Field(min_length=64, max_length=64)
    source_extraction_version: str
    fields: dict[str, AnalyzedField] = Field(default_factory=dict)
    special_clauses: list[SpecialClause] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    analysis_result_path: str | None = None
    reused: bool = False
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    @field_validator("analysis_result_path")
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\\", "/").strip()
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("분석 결과 경로는 안전한 상대 경로여야 합니다.")
        return normalized


class RegistryAnalysisResult(BaseModel):
    analysis_version: str = ANALYSIS_VERSION
    document_id: str
    source_document_ids: list[str] = Field(default_factory=list)
    conversation_id: str
    source_sha256: str = Field(min_length=64, max_length=64)
    source_extraction_version: str
    fields: dict[str, AnalyzedField] = Field(default_factory=dict)
    mortgages: list[RegistryRight] = Field(default_factory=list)
    restrictions: list[RegistryRight] = Field(default_factory=list)
    trusts: list[RegistryRight] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    analysis_result_path: str | None = None
    reused: bool = False
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    @field_validator("analysis_result_path")
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\\", "/").strip()
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("분석 결과 경로는 안전한 상대 경로여야 합니다.")
        return normalized


class ComparisonStatus(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNCERTAIN = "uncertain"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


class ComparisonItem(BaseModel):
    key: str
    label: str
    status: ComparisonStatus
    left_document_id: str | None = None
    right_document_id: str | None = None
    left_value: Any | None = None
    right_value: Any | None = None
    normalized_left: Any | None = None
    normalized_right: Any | None = None
    explanation: str
    warnings: list[str] = Field(default_factory=list)


class DocumentComparisonResult(BaseModel):
    comparison_version: str = COMPARISON_VERSION
    analysis_version: str = ANALYSIS_VERSION
    conversation_id: str
    lease_document_id: str | None = None
    registry_document_id: str | None = None
    comparisons: list[ComparisonItem] = Field(default_factory=list)
    triggered_issue_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    comparison_result_path: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("comparison_result_path")
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\\", "/").strip()
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("비교 결과 경로는 안전한 상대 경로여야 합니다.")
        return normalized


class DocumentSlotUpdate(BaseModel):
    issue_id: str
    slot_key: str
    status: AnalysisValueStatus
    value: Any | None = None
    evidence_text: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    document_ids: list[str] = Field(default_factory=list)
    not_applicable: bool = False


class StateMappingRecord(BaseModel):
    issue_id: str
    slot_key: str
    previous_status: str
    current_status: str
    previous_value: Any | None = None
    current_value: Any | None = None
    conflict_created: bool = False


class StateMappingSummary(BaseModel):
    added_issue_ids: list[str] = Field(default_factory=list)
    applied: list[StateMappingRecord] = Field(default_factory=list)
    ignored: list[str] = Field(default_factory=list)
    risk_level: str | None = None


class ConversationDocumentAnalysisResponse(BaseModel):
    lease_analyses: list[LeaseAnalysisResult] = Field(default_factory=list)
    registry_analyses: list[RegistryAnalysisResult] = Field(default_factory=list)
    comparison: DocumentComparisonResult | None = None
    state_mapping: StateMappingSummary = Field(default_factory=StateMappingSummary)
    state: Any | None = None
    warnings: list[str] = Field(default_factory=list)
