"""A파트 API에서 사용하는 공통 오류 코드와 예외 변환."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class APIErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class APIErrorResponse(BaseModel):
    success: bool = False
    error: APIErrorBody


class APartAPIError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}
        super().__init__(message)

    def response(self) -> APIErrorResponse:
        return APIErrorResponse(
            error=APIErrorBody(
                code=self.code,
                message=self.message,
                retryable=self.retryable,
                details=self.details,
            )
        )


class ConversationAccessDeniedError(PermissionError):
    pass


def translate_a_part_exception(error: Exception) -> APartAPIError:
    """내부 예외를 프론트엔드가 처리할 수 있는 안정적인 오류로 바꾼다."""

    from backend.app.consultation.a_part.input_validation import (
        ChatInputValidationError,
    )
    from backend.app.consultation.a_part.router import (
        UnsupportedConsultationIssueError,
    )
    from backend.app.consultation.a_part.store import (
        ConversationAlreadyExistsError,
        ConversationNotFoundError,
        ConversationStoreError,
    )
    from backend.app.documents.analysis.service import (
        ExtractionRequiredError,
        UnsupportedAnalysisDocumentTypeError,
    )
    from backend.app.documents.ocr import (
        OCRError,
        OCRLanguageMissingError,
        OCRTimeoutError,
        OCRUnavailableError,
    )
    from backend.app.documents.pdf_extractor import (
        CorruptedPDFError,
        EncryptedPDFError,
        PDFExtractionError,
        RenderedPageTooLargeError,
        TooManyPagesError,
    )
    from backend.app.documents.storage import (
        DocumentNotFoundError,
        DocumentStorageError,
        DuplicateDocumentTypeConflictError,
    )
    from backend.app.documents.validation import (
        DocumentTooLargeError,
        DocumentTypeMismatchError,
        DocumentValidationError,
        EmptyDocumentError,
        UnsupportedDocumentFormatError,
    )
    from backend.app.llm.a_part import (
        RAGAnswerGenerationError,
        RAGAnswerValidationError,
        RAGEvidenceInsufficientError,
        RAGEvidenceNotFoundError,
        RAGSearchUnavailableError,
    )

    if isinstance(error, APartAPIError):
        return error
    if isinstance(error, ChatInputValidationError):
        return APartAPIError(
            status_code=422,
            code=error.code,
            message=str(error),
            retryable=True,
        )
    if isinstance(error, UnsupportedConsultationIssueError):
        return APartAPIError(
            status_code=422,
            code="OUT_OF_SCOPE_QUERY",
            message=(
                "현재 상담은 계약 진행·입주 초기의 계약서와 등기부등본 관련 질문을 지원합니다. "
                "계약 상대방, 계좌, 권리관계, 계약 조건 또는 계약 직후 절차를 구체적으로 적어 주세요."
            ),
            retryable=True,
        )
    if isinstance(error, ConversationNotFoundError):
        return APartAPIError(
            status_code=404,
            code="CONVERSATION_NOT_FOUND",
            message="상담을 찾을 수 없습니다. 새 상담을 시작해 주세요.",
            retryable=False,
        )
    if isinstance(error, ConversationAccessDeniedError):
        return APartAPIError(
            status_code=403,
            code="CONVERSATION_ACCESS_DENIED",
            message="이 상담에 접근할 권한이 없습니다.",
        )
    if isinstance(error, ConversationAlreadyExistsError):
        return APartAPIError(
            status_code=409,
            code="CONVERSATION_ALREADY_EXISTS",
            message="이미 존재하는 상담입니다.",
        )
    if isinstance(error, ConversationStoreError):
        return APartAPIError(
            status_code=503,
            code="DATABASE_ERROR",
            message="상담 상태 데이터베이스를 사용할 수 없습니다.",
            retryable=True,
        )
    if isinstance(error, EmptyDocumentError):
        return APartAPIError(
            status_code=422,
            code="EMPTY_DOCUMENT",
            message=str(error),
            retryable=True,
        )
    if isinstance(error, DocumentTooLargeError):
        return APartAPIError(
            status_code=413,
            code="PDF_TOO_LARGE",
            message=str(error),
            retryable=True,
        )
    if isinstance(error, UnsupportedAnalysisDocumentTypeError):
        return APartAPIError(
            status_code=415,
            code="UNSUPPORTED_DOCUMENT_TYPE",
            message="계약서 또는 등기부등본 PDF만 업로드할 수 있습니다.",
            retryable=True,
        )
    if isinstance(error, UnsupportedDocumentFormatError):
        return APartAPIError(
            status_code=415,
            code="INVALID_DOCUMENT",
            message=str(error),
            retryable=True,
        )
    if isinstance(error, DocumentTypeMismatchError):
        return APartAPIError(
            status_code=415,
            code="INVALID_PDF",
            message=str(error),
            retryable=True,
        )
    if isinstance(error, DuplicateDocumentTypeConflictError):
        return APartAPIError(
            status_code=409,
            code="DOCUMENT_TYPE_CONFLICT",
            message=str(error),
            retryable=True,
        )
    if isinstance(error, DocumentNotFoundError):
        return APartAPIError(
            status_code=404,
            code="DOCUMENT_NOT_FOUND",
            message="문서를 찾을 수 없습니다.",
        )
    if isinstance(error, EncryptedPDFError):
        return APartAPIError(
            status_code=422,
            code="ENCRYPTED_PDF",
            message="암호가 설정된 PDF는 분석할 수 없습니다. 암호를 해제한 파일을 올려 주세요.",
            retryable=True,
        )
    if isinstance(error, CorruptedPDFError):
        return APartAPIError(
            status_code=422,
            code="CORRUPTED_PDF",
            message="PDF가 손상되어 읽을 수 없습니다. 파일을 다시 저장한 뒤 올려 주세요.",
            retryable=True,
        )
    if isinstance(error, TooManyPagesError):
        return APartAPIError(
            status_code=413,
            code="PDF_TOO_MANY_PAGES",
            message=str(error),
            retryable=True,
        )
    if isinstance(error, RenderedPageTooLargeError):
        return APartAPIError(
            status_code=413,
            code="PDF_PAGE_TOO_LARGE",
            message=str(error),
            retryable=True,
        )
    if isinstance(error, (OCRUnavailableError, OCRLanguageMissingError)):
        return APartAPIError(
            status_code=503,
            code="OCR_UNAVAILABLE",
            message="문서 OCR 환경을 사용할 수 없습니다. 서버 설정을 확인해 주세요.",
            retryable=True,
        )
    if isinstance(error, OCRTimeoutError):
        return APartAPIError(
            status_code=504,
            code="OCR_TIMEOUT",
            message="문서 글자 인식 시간이 초과됐습니다. 더 선명하거나 작은 PDF로 다시 시도해 주세요.",
            retryable=True,
        )
    if isinstance(error, (OCRError, PDFExtractionError, ExtractionRequiredError)):
        return APartAPIError(
            status_code=422,
            code="DOCUMENT_EXTRACTION_FAILED",
            message="문서의 글자를 충분히 읽지 못했습니다. 원본이 선명한 PDF인지 확인해 주세요.",
            retryable=True,
        )
    if isinstance(error, RAGEvidenceNotFoundError):
        return APartAPIError(
            status_code=422,
            code="RAG_EVIDENCE_NOT_FOUND",
            message="현재 질문에 직접 연결되는 근거를 찾지 못했습니다. 상황을 조금 더 구체적으로 입력해 주세요.",
            retryable=True,
        )
    if isinstance(error, RAGEvidenceInsufficientError):
        return APartAPIError(
            status_code=422,
            code="RAG_EVIDENCE_INSUFFICIENT",
            message="답변에 필요한 근거가 충분하지 않습니다. 관련 사실이나 문서를 추가해 주세요.",
            retryable=True,
        )
    if isinstance(error, RAGSearchUnavailableError):
        return APartAPIError(
            status_code=503,
            code="RAG_SEARCH_FAILED",
            message="법률 근거 검색을 일시적으로 사용할 수 없습니다.",
            retryable=True,
        )
    if isinstance(error, RAGAnswerGenerationError):
        return APartAPIError(
            status_code=503,
            code="LLM_SERVICE_ERROR",
            message="상담 답변을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            retryable=True,
        )
    if isinstance(error, RAGAnswerValidationError):
        return APartAPIError(
            status_code=502,
            code="INVALID_LLM_RESPONSE",
            message="생성된 답변의 필수 항목을 확인하지 못했습니다. 다시 시도해 주세요.",
            retryable=True,
        )
    if isinstance(error, DocumentValidationError):
        return APartAPIError(
            status_code=422,
            code="INVALID_DOCUMENT",
            message=str(error),
            retryable=True,
        )
    if isinstance(error, DocumentStorageError):
        return APartAPIError(
            status_code=500,
            code="DOCUMENT_STORAGE_ERROR",
            message="문서를 저장하거나 불러오지 못했습니다.",
            retryable=True,
        )
    if error.__class__.__module__.startswith("psycopg2"):
        return APartAPIError(
            status_code=503,
            code="DATABASE_ERROR",
            message="문서 또는 상담 데이터베이스를 사용할 수 없습니다.",
            retryable=True,
        )
    if isinstance(error, TimeoutError):
        return APartAPIError(
            status_code=504,
            code="REQUEST_TIMEOUT",
            message="요청 처리 시간이 초과됐습니다. 다시 시도해 주세요.",
            retryable=True,
        )
    if isinstance(error, ValueError):
        return APartAPIError(
            status_code=422,
            code="INVALID_REQUEST",
            message=str(error),
            retryable=True,
        )

    return APartAPIError(
        status_code=500,
        code="INTERNAL_SERVER_ERROR",
        message="서버에서 요청을 처리하지 못했습니다.",
        retryable=True,
    )
