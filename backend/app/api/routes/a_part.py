"""A파트 상담·계약서·등기부등본 백엔드 API.

기존 RAG·대화 상태·문서 분석 모듈을 FastAPI에 연결한다.
계약서와 등기부등본 PDF만 지원하며, 내부 예외는 공통 오류 코드로 변환한다.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Query,
    UploadFile,
)
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.app.api.a_part_errors import (
    APartAPIError,
    ConversationAccessDeniedError,
    translate_a_part_exception,
)
from backend.app.consultation.a_part.chatbot_service import (
    APartChatbotService,
    ChatbotTurnRequest,
    ChatbotTurnResult,
)
from backend.app.consultation.a_part.input_validation import (
    normalize_chat_input,
    requests_document_review,
)
from backend.app.consultation.a_part.models import (
    ConversationState,
    create_conversation_state,
)
from backend.app.consultation.a_part.service import APartConversationService
from backend.app.consultation.a_part.store import PostgresConversationStore
from backend.app.consultation.a_part.document_service import APartDocumentUploadService
from backend.app.core.config import settings
from backend.app.consultation.a_part.state_updater import ExtractedSlotUpdate
from backend.app.documents.models import DocumentType
from backend.app.documents.db_storage import DocumentDatabaseRepository


router = APIRouter(prefix="/chat/a", tags=["a_part"])

# A파트 단독 시나리오 검증용 임시 사용자다.
# 팀 인증 API가 연결되면 각 라우트의 의존성을 get_current_user로 되돌린다.
_A_PART_GUEST_USER_ID = 0


def get_a_part_guest_user() -> SimpleNamespace:
    return SimpleNamespace(id=_A_PART_GUEST_USER_ID)

_SUPPORTED_DOCUMENT_TYPES = {
    DocumentType.LEASE_CONTRACT,
    DocumentType.REGISTRY,
}
_DEFAULT_CONVERSATION_SERVICE = APartConversationService(
    store=PostgresConversationStore(settings.database_url)
)
_DEFAULT_CHATBOT_SERVICE = APartChatbotService(
    conversation_service=_DEFAULT_CONVERSATION_SERVICE,
    document_service=APartDocumentUploadService(
        conversation_service=_DEFAULT_CONVERSATION_SERVICE,
        database_repository=DocumentDatabaseRepository(settings.database_url),
    ),
)


class SuccessEnvelope(BaseModel):
    success: bool = True
    data: Any


class ConversationCreateRequest(BaseModel):
    primary_issue_id: str = "q15_after_contract_procedure"
    related_issue_ids: list[str] = Field(default_factory=list, max_length=2)


class ChatTurnAPIRequest(BaseModel):
    question: str
    conversation_id: str | None = None
    issue_id: str | None = None
    related_issue_ids: list[str] = Field(default_factory=list, max_length=2)
    checklist_updates: list[ExtractedSlotUpdate | dict[str, Any]] = Field(
        default_factory=list,
        max_length=30,
    )
    document_ids: list[str] = Field(default_factory=list, max_length=10)
    analyze_documents: bool = True
    force_document_analysis: bool = False


class AnalyzeDocumentsRequest(BaseModel):
    document_ids: list[str] = Field(default_factory=list, max_length=10)
    force: bool = False


def get_a_part_chatbot_service() -> APartChatbotService:
    """테스트에서 교체할 수 있는 서비스 의존성."""

    return _DEFAULT_CHATBOT_SERVICE


def _user_id(user: Any) -> int:
    value = getattr(user, "id", None)
    if value is None:
        raise APartAPIError(
            status_code=401,
            code="AUTHENTICATION_REQUIRED",
            message="로그인이 필요합니다.",
        )
    return int(value)


def _assert_conversation_access(
    service: APartChatbotService,
    *,
    conversation_id: str,
    user_id: int,
    claim_unowned: bool = False,
) -> ConversationState:
    state = service.conversation_service.get_state(conversation_id)
    if state.owner_user_id is None and claim_unowned:
        state.owner_user_id = user_id
        return service.conversation_service.store.save(state)
    if state.owner_user_id != user_id:
        raise ConversationAccessDeniedError(
            f"conversation owner mismatch: {conversation_id}"
        )
    return state


def _claim_new_result(
    service: APartChatbotService,
    *,
    result: ChatbotTurnResult,
    user_id: int,
) -> ChatbotTurnResult:
    state = service.conversation_service.get_state(result.conversation_id)
    if state.owner_user_id not in {None, user_id}:
        raise ConversationAccessDeniedError(
            f"conversation owner mismatch: {result.conversation_id}"
        )
    state.owner_user_id = user_id
    stored = service.conversation_service.store.save(state)

    consultation = result.consultation.model_copy(update={"state": stored})
    document_analysis = result.document_analysis
    if document_analysis is not None and document_analysis.state is not None:
        document_analysis = document_analysis.model_copy(update={"state": stored})
    return result.model_copy(
        update={
            "consultation": consultation,
            "document_analysis": document_analysis,
        }
    )


async def _call(function, /, *args, **kwargs):
    try:
        return await run_in_threadpool(function, *args, **kwargs)
    except Exception as error:
        raise translate_a_part_exception(error) from error


@router.post("/conversations", response_model=SuccessEnvelope, status_code=201)
async def create_a_part_conversation(
    request: ConversationCreateRequest,
    user=Depends(get_a_part_guest_user),
    service: APartChatbotService = Depends(get_a_part_chatbot_service),
):
    """파일 업로드 전에 사용할 빈 A파트 상담 상태를 만든다."""

    try:
        state = create_conversation_state(
            primary_issue_id=request.primary_issue_id,
            related_issue_ids=request.related_issue_ids,
        )
        state.owner_user_id = _user_id(user)
        stored = service.conversation_service.store.create(state)
        return SuccessEnvelope(data=stored)
    except Exception as error:
        raise translate_a_part_exception(error) from error


@router.post("/turn", response_model=SuccessEnvelope)
async def handle_a_part_turn(
    request: ChatTurnAPIRequest,
    user=Depends(get_a_part_guest_user),
    service: APartChatbotService = Depends(get_a_part_chatbot_service),
):
    """자연어 질문과 기존 문서·상담 상태를 결합해 한 턴을 처리한다."""

    user_id = _user_id(user)
    try:
        normalized_question = normalize_chat_input(
            request.question,
            is_follow_up=request.conversation_id is not None,
        )
        current_state = None
        if request.conversation_id:
            current_state = _assert_conversation_access(
                service,
                conversation_id=request.conversation_id,
                user_id=user_id,
            )

        has_documents = bool(current_state and current_state.documents)
        if requests_document_review(normalized_question) and not has_documents:
            raise APartAPIError(
                status_code=422,
                code="DOCUMENT_REQUIRED",
                message="분석할 계약서 또는 등기부등본 PDF를 먼저 업로드해 주세요.",
                retryable=True,
            )

        internal_request = ChatbotTurnRequest(
            question=normalized_question,
            conversation_id=request.conversation_id,
            issue_id=request.issue_id,
            related_issue_ids=request.related_issue_ids,
            checklist_updates=request.checklist_updates,
            document_ids=request.document_ids,
            analyze_documents=request.analyze_documents,
            force_document_analysis=request.force_document_analysis,
        )
        result = await _call(service.handle, internal_request)
        if result.is_new_conversation:
            result = _claim_new_result(
                service,
                result=result,
                user_id=user_id,
            )
        return SuccessEnvelope(data=result)
    except Exception as error:
        if isinstance(error, APartAPIError):
            raise
        raise translate_a_part_exception(error) from error


@router.get(
    "/conversations/{conversation_id}",
    response_model=SuccessEnvelope,
)
async def get_a_part_conversation(
    conversation_id: str,
    user=Depends(get_a_part_guest_user),
    service: APartChatbotService = Depends(get_a_part_chatbot_service),
):
    try:
        state = _assert_conversation_access(
            service,
            conversation_id=conversation_id,
            user_id=_user_id(user),
        )
        return SuccessEnvelope(data=state)
    except Exception as error:
        raise translate_a_part_exception(error) from error


@router.delete(
    "/conversations/{conversation_id}",
    response_model=SuccessEnvelope,
)
async def delete_a_part_conversation(
    conversation_id: str,
    user=Depends(get_a_part_guest_user),
    service: APartChatbotService = Depends(get_a_part_chatbot_service),
):
    """상담 상태와 연결된 파일·문서 처리 DB 결과를 함께 삭제한다."""

    try:
        state = _assert_conversation_access(
            service,
            conversation_id=conversation_id,
            user_id=_user_id(user),
        )
        cleanup = await _call(
            service.document_service.delete_conversation_artifacts,
            conversation_id=conversation_id,
        )
        deleted = service.conversation_service.delete(conversation_id)
        return SuccessEnvelope(
            data={
                "conversation_id": conversation_id,
                "deleted": deleted,
                "cleanup": cleanup,
                "warnings": [],
            }
        )
    except Exception as error:
        if isinstance(error, APartAPIError):
            raise
        raise translate_a_part_exception(error) from error


@router.post(
    "/conversations/{conversation_id}/documents",
    response_model=SuccessEnvelope,
    status_code=201,
)
async def upload_a_part_document(
    conversation_id: str,
    document_type: str = Form(...),
    file: UploadFile = File(...),
    extract_text: bool = Query(default=True),
    force_extraction: bool = Query(default=False),
    user=Depends(get_a_part_guest_user),
    service: APartChatbotService = Depends(get_a_part_chatbot_service),
):
    """계약서 또는 등기부등본 PDF를 저장하고 기본적으로 텍스트까지 추출한다."""

    try:
        _assert_conversation_access(
            service,
            conversation_id=conversation_id,
            user_id=_user_id(user),
        )
        try:
            normalized_type = DocumentType(document_type)
        except ValueError as error:
            raise APartAPIError(
                status_code=415,
                code="UNSUPPORTED_DOCUMENT_TYPE",
                message="계약서(lease_contract) 또는 등기부등본(registry)만 업로드할 수 있습니다.",
                retryable=True,
            ) from error
        if normalized_type not in _SUPPORTED_DOCUMENT_TYPES:
            raise APartAPIError(
                status_code=415,
                code="UNSUPPORTED_DOCUMENT_TYPE",
                message="계약서(lease_contract) 또는 등기부등본(registry)만 업로드할 수 있습니다.",
                retryable=True,
            )
        if not file.filename:
            raise APartAPIError(
                status_code=422,
                code="EMPTY_FILENAME",
                message="업로드할 PDF 파일을 선택해 주세요.",
                retryable=True,
            )

        upload_result = await _call(
            service.document_service.upload_stream,
            conversation_id=conversation_id,
            document_type=normalized_type,
            filename=file.filename,
            content_type=file.content_type,
            stream=file.file,
        )
        extraction = None
        if extract_text:
            extraction = await _call(
                service.document_service.extract_document,
                conversation_id=conversation_id,
                document_id=upload_result.document.document_id,
                force=force_extraction,
            )
        return SuccessEnvelope(
            data={
                "upload": upload_result,
                "extraction": extraction,
            }
        )
    except Exception as error:
        if isinstance(error, APartAPIError):
            raise
        raise translate_a_part_exception(error) from error
    finally:
        await file.close()


@router.get(
    "/conversations/{conversation_id}/documents",
    response_model=SuccessEnvelope,
)
async def list_a_part_documents(
    conversation_id: str,
    user=Depends(get_a_part_guest_user),
    service: APartChatbotService = Depends(get_a_part_chatbot_service),
):
    try:
        _assert_conversation_access(
            service,
            conversation_id=conversation_id,
            user_id=_user_id(user),
        )
        documents = service.document_service.list_documents(conversation_id)
        return SuccessEnvelope(data=documents)
    except Exception as error:
        raise translate_a_part_exception(error) from error


@router.delete(
    "/conversations/{conversation_id}/documents/{document_id}",
    response_model=SuccessEnvelope,
)
async def delete_a_part_document(
    conversation_id: str,
    document_id: str,
    user=Depends(get_a_part_guest_user),
    service: APartChatbotService = Depends(get_a_part_chatbot_service),
):
    try:
        _assert_conversation_access(
            service,
            conversation_id=conversation_id,
            user_id=_user_id(user),
        )
        removed = await _call(
            service.document_service.delete_document,
            conversation_id=conversation_id,
            document_id=document_id,
        )
        return SuccessEnvelope(data=removed)
    except Exception as error:
        if isinstance(error, APartAPIError):
            raise
        raise translate_a_part_exception(error) from error


@router.post(
    "/conversations/{conversation_id}/documents/{document_id}/extract",
    response_model=SuccessEnvelope,
)
async def extract_a_part_document(
    conversation_id: str,
    document_id: str,
    force: bool = Query(default=False),
    user=Depends(get_a_part_guest_user),
    service: APartChatbotService = Depends(get_a_part_chatbot_service),
):
    try:
        _assert_conversation_access(
            service,
            conversation_id=conversation_id,
            user_id=_user_id(user),
        )
        result = await _call(
            service.document_service.extract_document,
            conversation_id=conversation_id,
            document_id=document_id,
            force=force,
        )
        return SuccessEnvelope(data=result)
    except Exception as error:
        if isinstance(error, APartAPIError):
            raise
        raise translate_a_part_exception(error) from error


@router.post(
    "/conversations/{conversation_id}/documents/analyze",
    response_model=SuccessEnvelope,
)
async def analyze_a_part_documents(
    conversation_id: str,
    request: AnalyzeDocumentsRequest,
    user=Depends(get_a_part_guest_user),
    service: APartChatbotService = Depends(get_a_part_chatbot_service),
):
    try:
        _assert_conversation_access(
            service,
            conversation_id=conversation_id,
            user_id=_user_id(user),
        )
        result = await _call(
            service.document_service.analyze_documents,
            conversation_id=conversation_id,
            document_ids=request.document_ids or None,
            force=request.force,
        )
        return SuccessEnvelope(data=result)
    except Exception as error:
        if isinstance(error, APartAPIError):
            raise
        raise translate_a_part_exception(error) from error
