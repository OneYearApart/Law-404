"""A파트 텍스트 상담 상태와 q01~q20 슬롯 서비스.

무거운 RAG·OpenAI 모듈은 실제 서비스 함수를 호출할 때만 불러온다.
"""

from typing import Any

from app.consultation.a_part.issues import (
    ISSUE_DEFINITIONS,
    IssueDefinition,
    SlotDefinition,
    get_issue_definition,
    get_supported_issue_ids,
)
from app.consultation.a_part.models import (
    ConversationMessage,
    ConversationState,
    FactSource,
    MessageRole,
    SlotState,
    SlotStatus,
    add_issue_to_state,
    create_conversation_state,
)
from app.consultation.a_part.store import (
    ConversationNotFoundError,
    MemoryConversationStore,
)


def handle_consultation(*args: Any, **kwargs: Any) -> Any:
    from app.consultation.a_part.service import handle_consultation as _handle
    return _handle(*args, **kwargs)


def get_conversation_state(conversation_id: str) -> ConversationState:
    from app.consultation.a_part.service import get_conversation_state as _get
    return _get(conversation_id)


def attach_document_to_conversation(
    conversation_id: str,
    document: Any,
) -> ConversationState:
    from app.consultation.a_part.service import (
        attach_document_to_conversation as _attach,
    )
    return _attach(conversation_id, document)



def update_conversation_document(
    conversation_id: str,
    document: Any,
) -> ConversationState:
    from app.consultation.a_part.service import (
        update_conversation_document as _update,
    )
    return _update(conversation_id, document)


def analyze_conversation_documents(*args: Any, **kwargs: Any) -> Any:
    from app.consultation.a_part.document_service import (
        analyze_conversation_documents as _analyze,
    )
    return _analyze(*args, **kwargs)


def reset_conversation(conversation_id: str) -> ConversationState:
    from app.consultation.a_part.service import reset_conversation as _reset
    return _reset(conversation_id)


def handle_chatbot_turn(*args: Any, **kwargs: Any) -> Any:
    from app.consultation.a_part.chatbot_service import (
        APartChatbotService,
        ChatbotTurnRequest,
    )
    service = APartChatbotService()
    request = (
        args[0]
        if args and isinstance(args[0], ChatbotTurnRequest)
        else ChatbotTurnRequest(**kwargs)
    )
    return service.handle(request)


__all__ = [
    "ISSUE_DEFINITIONS",
    "ConversationMessage",
    "ConversationNotFoundError",
    "ConversationState",
    "FactSource",
    "IssueDefinition",
    "MemoryConversationStore",
    "MessageRole",
    "SlotDefinition",
    "SlotState",
    "SlotStatus",
    "add_issue_to_state",
    "analyze_conversation_documents",
    "attach_document_to_conversation",
    "create_conversation_state",
    "get_conversation_state",
    "get_issue_definition",
    "get_supported_issue_ids",
    "handle_chatbot_turn",
    "handle_consultation",
    "reset_conversation",
    "update_conversation_document",
]
