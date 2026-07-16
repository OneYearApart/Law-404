"""계약서·등기부 필드 분석과 문서 비교 기능."""

from app.documents.analysis.comparison import compare_documents
from app.documents.analysis.lease_analyzer import analyze_lease_contract
from app.documents.analysis.models import (
    ANALYSIS_VERSION,
    COMPARISON_VERSION,
    AnalysisEvidence,
    AnalysisValueStatus,
    AnalyzedField,
    ComparisonItem,
    ComparisonStatus,
    ConversationDocumentAnalysisResponse,
    DocumentComparisonResult,
    DocumentSlotUpdate,
    LeaseAnalysisResult,
    RegistryAnalysisResult,
    RegistryRight,
    SpecialClause,
    StateMappingSummary,
)
from app.documents.analysis.registry_analyzer import analyze_registry
from app.documents.analysis.service import (
    DocumentAnalysisService,
    ExtractionRequiredError,
    UnsupportedAnalysisDocumentTypeError,
)
from app.documents.analysis.storage import (
    AnalysisResultNotFoundError,
    DocumentAnalysisStorage,
)

__all__ = [
    "ANALYSIS_VERSION",
    "COMPARISON_VERSION",
    "AnalysisEvidence",
    "AnalysisResultNotFoundError",
    "AnalysisValueStatus",
    "AnalyzedField",
    "ComparisonItem",
    "ComparisonStatus",
    "ConversationDocumentAnalysisResponse",
    "DocumentAnalysisService",
    "DocumentAnalysisStorage",
    "DocumentComparisonResult",
    "DocumentSlotUpdate",
    "ExtractionRequiredError",
    "LeaseAnalysisResult",
    "RegistryAnalysisResult",
    "RegistryRight",
    "SpecialClause",
    "StateMappingSummary",
    "UnsupportedAnalysisDocumentTypeError",
    "analyze_lease_contract",
    "analyze_registry",
    "compare_documents",
]
