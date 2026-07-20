"""A파트 상담·계약서·등기부등본 백엔드 API.

기존 RAG·대화 상태·문서 분석 모듈을 FastAPI에 연결한다.
계약서와 등기부등본 PDF만 지원하며, 내부 예외는 공통 오류 코드로 변환한다.
"""

from __future__ import annotations

from typing import Any

from app.api.a_part_errors import (
    APartAPIError,
    ConversationAccessDeniedError,
    translate_a_part_exception,
)
from app.auth.dependencies import get_current_user
from app.consultation.a_part.chatbot_service import (
    APartChatbotService,
    ChatbotTurnRequest,
    ChatbotTurnResult,
)
from app.consultation.a_part.document_service import APartDocumentUploadService
from app.consultation.a_part.input_validation import (
    normalize_chat_input,
    requests_document_review,
)
from app.consultation.a_part.models import (
    ConversationState,
    FactSource,
    SlotStatus,
    create_conversation_state,
)
from app.consultation.a_part.service import APartConversationService
from app.consultation.a_part.state_updater import ExtractedSlotUpdate
from app.consultation.a_part.state_policy import owner_proxy_progress_display
from app.consultation.a_part.store import SharedConversationStore
from app.conversations.summarizer import maybe_summarize_conversation
from app.core.config import settings
from app.documents.db_storage import DocumentDatabaseRepository
from app.documents.models import DocumentType
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

router = APIRouter(prefix="/chat/a", tags=["a_part"])

_SUPPORTED_DOCUMENT_TYPES = {
    DocumentType.LEASE_CONTRACT,
    DocumentType.REGISTRY,
}
_DEFAULT_CONVERSATION_SERVICE = APartConversationService(
    store=SharedConversationStore(part="a")
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
    attached_document_ids: list[str] = Field(default_factory=list, max_length=10)
    analyze_documents: bool = False
    force_document_analysis: bool = False


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


_INTERNAL_WARNING_MARKERS = (
    "슬롯",
    "RAG",
    "rag",
    "document_ids",
    "generation_status",
    "검색기",
)


def _public_warnings(items: list[str]) -> list[str]:
    result: list[str] = []
    for item in items:
        normalized = str(item or "").strip()
        if not normalized:
            continue
        if any(marker in normalized for marker in _INTERNAL_WARNING_MARKERS):
            continue
        if normalized not in result:
            result.append(normalized)
    return result


def _serialize_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    enum_value = getattr(value, "value", None)
    if enum_value is not None:
        return enum_value
    return value




def _progress_value(value: Any, status: Any) -> str:
    status_value = str(getattr(status, "value", status) or "")
    if status_value == "not_applicable":
        return "해당 없음"
    if status_value == "uncertain":
        return "확인하지 못함"
    if value is True:
        return "확인함"
    if value is False:
        return "확인하지 못함"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value or "확인함")


def _is_answered_but_unresolved(slot: Any) -> bool:
    if slot.status == SlotStatus.CONFIRMED and slot.value is False:
        return True
    return (
        slot.status == SlotStatus.UNCERTAIN
        and slot.source == FactSource.USER
    )


def _snapshot_question(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    question = snapshot.get("next_question")
    if isinstance(question, dict) and question.get("question"):
        return question

    follow_ups = snapshot.get("follow_up_questions") or []
    if follow_ups and isinstance(follow_ups[0], dict):
        return follow_ups[0]
    return None


def _build_answer_history(
    state: ConversationState,
    pending_snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """저장된 턴 스냅샷에서 질문과 실제 사용자 답변을 순서대로 복원한다."""

    snapshots = list(state.turn_history or [])
    if pending_snapshot is not None:
        snapshots.append(pending_snapshot)
    history: list[dict[str, Any]] = []

    # 첫 스냅샷의 user_message는 최초 상담 질문이다.
    # 다음 스냅샷의 user_message부터 직전 next_question에 대한 답변이다.
    for index in range(1, len(snapshots)):
        previous = snapshots[index - 1]
        current = snapshots[index]
        question = _snapshot_question(previous)
        if not question:
            continue

        issue_id = str(question.get("issue_id") or "")
        slot_key = str(question.get("slot_key") or "")
        applied_updates = current.get("applied_updates") or []
        matched_update = next(
            (
                update
                for update in applied_updates
                if str(update.get("issue_id") or "") == issue_id
                and str(update.get("slot_key") or "") == slot_key
            ),
            None,
        )
        if matched_update is None:
            continue

        status = matched_update.get("current_status") or question.get("status")
        value = matched_update.get("current_value")
        user_answer = str(current.get("user_message") or "").strip()
        if not user_answer:
            continue

        history.append({
            "order": len(history) + 1,
            "issue_id": issue_id,
            "slot_key": slot_key,
            "question_key": question.get("question_key"),
            "label": question.get("label") or slot_key,
            "question": question.get("question") or question.get("label") or slot_key,
            "answer_text": user_answer,
            "status": str(getattr(status, "value", status) or ""),
            "value": value,
            "display_value": _progress_value(value, status),
        })

    return history


def _build_consultation_progress(
    consultation: Any,
    pending_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = consultation.state
    confirmed_items: list[dict[str, Any]] = []
    unresolved_items: list[dict[str, Any]] = []
    remaining_items: list[dict[str, Any]] = []
    conflict_items: list[dict[str, Any]] = []

    for issue_id in state.all_issue_ids:
        for slot in state.issue_slots.get(issue_id, {}).values():
            default_display_value = _progress_value(slot.value, slot.status)
            display_label, display_value = owner_proxy_progress_display(
                state,
                slot,
                default_display_value=default_display_value,
            )
            item = {
                "issue_id": issue_id,
                "slot_key": slot.key,
                "label": display_label,
                "status": slot.status.value,
                "source": slot.source.value if slot.source else None,
            }
            if slot.status == SlotStatus.CONFLICT:
                conflict_items.append(item)
            elif (
                issue_id == "q01_owner_proxy"
                and slot.status == SlotStatus.NOT_APPLICABLE
            ):
                unresolved_items.append({
                    **item,
                    "value": None,
                    "display_value": "확인하지 못함",
                })
            elif _is_answered_but_unresolved(slot):
                unresolved_items.append({
                    **item,
                    "value": slot.value,
                    "display_value": display_value,
                })
            elif slot.is_confirmed():
                confirmed_items.append({
                    **item,
                    "value": slot.value,
                    "display_value": display_value,
                })
            else:
                remaining_items.append(item)

    next_question = (
        consultation.follow_up_questions[0].model_dump(mode="json")
        if consultation.follow_up_questions
        else None
    )
    progress = {
        "completed_count": len(confirmed_items) + len(unresolved_items),
        "total_count": (
            len(confirmed_items)
            + len(unresolved_items)
            + len(remaining_items)
            + len(conflict_items)
        ),
        "confirmed_items": confirmed_items,
        "unresolved_items": unresolved_items,
        "remaining_items": remaining_items,
        "conflict_items": conflict_items,
        "answer_history": _build_answer_history(
            state,
            pending_snapshot=pending_snapshot,
        ),
        "risk_level": consultation.risk_assessment.risk_level,
        "is_complete": next_question is None,
    }
    return progress


def _build_turn_snapshot(
    *,
    question: str,
    result: ChatbotTurnResult,
    attached_document_ids: list[str] | None = None,
) -> dict[str, Any]:
    consultation = result.consultation
    rag_response = consultation.rag_response
    answer = getattr(rag_response, "answer", None)
    answer_data = (
        answer.model_dump(mode="json")
        if hasattr(answer, "model_dump")
        else dict(answer or {})
    )
    attached_id_set = {
        str(document_id).strip()
        for document_id in (attached_document_ids or [])
        if str(document_id).strip()
    }
    attached_documents = [
        {
            "document_id": document.document_id,
            "original_filename": document.original_filename,
            "document_type": document.document_type.value
            if hasattr(document.document_type, "value")
            else str(document.document_type),
        }
        for document in consultation.state.documents
        if document.document_id in attached_id_set
    ]

    snapshot = {
        "user_message": question,
        "attached_documents": attached_documents,
        "answer": answer_data,
        "is_new_conversation": result.is_new_conversation,
        "applied_updates": [
            _serialize_value(item) for item in consultation.applied_updates
        ],
        "known_facts": list(consultation.known_facts),
        "missing_facts": list(consultation.missing_facts),
        "conflict_facts": list(consultation.conflict_facts),
        "follow_up_questions": [
            _serialize_value(item) for item in consultation.follow_up_questions[:1]
        ],
        "risk_assessment": _serialize_value(consultation.risk_assessment),
        "warnings": _public_warnings(
            [*result.warnings, *consultation.warnings]
        ),
        "processing_status": _serialize_value(result.processing_status),
        "answer_ready": result.answer_ready,
        "turn_count": consultation.state.turn_count,
        "next_question": (
            consultation.follow_up_questions[0].model_dump(mode="json")
            if consultation.follow_up_questions
            else None
        ),
        "is_complete": not consultation.follow_up_questions,
    }
    snapshot["consultation_progress"] = _build_consultation_progress(
        consultation,
        pending_snapshot=snapshot,
    )
    return snapshot


def _persist_turn_snapshot(
    service: APartChatbotService,
    *,
    question: str,
    result: ChatbotTurnResult,
    attached_document_ids: list[str] | None = None,
) -> ChatbotTurnResult:
    state = service.conversation_service.get_state(result.conversation_id)
    state.turn_history.append(
        _build_turn_snapshot(
            question=question,
            result=result,
            attached_document_ids=attached_document_ids,
        )
    )
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


@router.get("/conversations", response_model=SuccessEnvelope)
async def list_a_part_conversations(
    user=Depends(get_current_user),
    service: APartChatbotService = Depends(get_a_part_chatbot_service),
):
    """로그인한 사용자의 최근 A파트 상담 목록만 반환한다."""

    try:
        store = service.conversation_service.store
        if not isinstance(store, SharedConversationStore):
            return SuccessEnvelope(data=[])
        rows = await _call(store.list_for_owner, _user_id(user))
        return SuccessEnvelope(data=rows)
    except Exception as error:
        raise translate_a_part_exception(error) from error


@router.post("/conversations", response_model=SuccessEnvelope, status_code=201)
async def create_a_part_conversation(
    request: ConversationCreateRequest,
    user=Depends(get_current_user),
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
    background_tasks: BackgroundTasks,
    user=Depends(get_current_user),
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
                message="분석할 임대차계약서 또는 등기부등본 PDF를 먼저 업로드해 주세요.",
                retryable=True,
            )

        internal_request = ChatbotTurnRequest(
            question=normalized_question,
            conversation_id=request.conversation_id,
            owner_user_id=user_id,
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
        result = await _call(
            _persist_turn_snapshot,
            service,
            question=normalized_question,
            result=result,
            attached_document_ids=request.attached_document_ids,
        )
        progress = _build_consultation_progress(result.consultation)
        next_question = (
            result.consultation.follow_up_questions[0].model_dump(mode="json")
            if result.consultation.follow_up_questions
            else None
        )
        result = result.model_copy(update={
            "consultation_progress": progress,
            "next_question": next_question,
            "is_complete": next_question is None,
        })

        turn_count = result.consultation.state.turn_count
        summary_interval = max(1, int(settings.summary_trigger_turns or 4))
        try:
            summary_conversation_id = int(result.conversation_id)
        except (TypeError, ValueError):
            summary_conversation_id = None
        if (
            summary_conversation_id is not None
            and (
                result.is_new_conversation
                or turn_count % summary_interval == 0
            )
        ):
            background_tasks.add_task(
                maybe_summarize_conversation,
                summary_conversation_id,
                user_id,
                1,
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
    user=Depends(get_current_user),
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
    user=Depends(get_current_user),
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
    user=Depends(get_current_user),
    service: APartChatbotService = Depends(get_a_part_chatbot_service),
):
    """계약서 또는 등기부등본 PDF를 분석 없이 첨부한다."""

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
        return SuccessEnvelope(data={"upload": upload_result})
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
    user=Depends(get_current_user),
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
    user=Depends(get_current_user),
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
