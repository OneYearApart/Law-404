"""A파트 텍스트 상담에서 유지하는 대화 상태 모델."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from backend.app.consultation.a_part.issues import get_issue_definition
from backend.app.documents.models import UploadedDocument


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SlotStatus(str, Enum):
    UNKNOWN = "unknown"
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"
    CONFLICT = "conflict"
    NOT_APPLICABLE = "not_applicable"


class FactSource(str, Enum):
    USER = "user"
    DOCUMENT = "document"
    SYSTEM = "system"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class SlotState(BaseModel):
    """한 확인 항목의 현재 값과 확인 상태."""

    key: str
    label: str
    question: str
    priority: int = Field(ge=1)
    risk_critical: bool = False

    value: Any | None = None
    status: SlotStatus = SlotStatus.UNKNOWN
    source: FactSource | None = None
    evidence_text: str | None = None
    conflicting_values: list[Any] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)

    def is_missing(self) -> bool:
        return self.status in {
            SlotStatus.UNKNOWN,
            SlotStatus.UNCERTAIN,
            SlotStatus.CONFLICT,
        }

    def is_confirmed(self) -> bool:
        return self.status in {
            SlotStatus.CONFIRMED,
            SlotStatus.NOT_APPLICABLE,
        }


class ConversationMessage(BaseModel):
    role: MessageRole
    content: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)


class ConversationState(BaseModel):
    """상담 하나에서 유지하는 전체 상태."""

    conversation_id: str = Field(default_factory=lambda: str(uuid4()))
    owner_user_id: int | None = None
    primary_issue_id: str
    related_issue_ids: list[str] = Field(default_factory=list)
    issue_slots: dict[str, dict[str, SlotState]] = Field(default_factory=dict)
    messages: list[ConversationMessage] = Field(default_factory=list)
    asked_question_keys: list[str] = Field(default_factory=list)
    last_risk_level: str | None = None
    last_answer: dict[str, Any] | None = None
    documents: list[UploadedDocument] = Field(default_factory=list)
    document_analysis_version: str | None = None
    document_comparison_result_path: str | None = None
    turn_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_issue_ids(self) -> "ConversationState":
        get_issue_definition(self.primary_issue_id)

        if self.primary_issue_id in self.related_issue_ids:
            raise ValueError(
                "primary_issue_id는 related_issue_ids에 중복될 수 없습니다."
            )

        if len(self.related_issue_ids) != len(set(self.related_issue_ids)):
            raise ValueError("related_issue_ids에 중복 값이 있습니다.")

        for issue_id in self.related_issue_ids:
            get_issue_definition(issue_id)

        document_ids: set[str] = set()
        for document in self.documents:
            if document.conversation_id != self.conversation_id:
                raise ValueError(
                    "첨부 문서의 conversation_id가 상담 상태와 다릅니다."
                )
            if document.document_id in document_ids:
                raise ValueError("documents에 중복 document_id가 있습니다.")
            document_ids.add(document.document_id)

        return self

    @property
    def all_issue_ids(self) -> tuple[str, ...]:
        return (self.primary_issue_id, *self.related_issue_ids)

    @property
    def initial_query(self) -> str | None:
        for message in self.messages:
            if message.role == MessageRole.USER:
                return message.content
        return None

    def touch(self) -> None:
        self.updated_at = utc_now()

    def append_message(self, role: MessageRole, content: str) -> None:
        normalized = content.strip()
        if not normalized:
            raise ValueError("대화 메시지는 빈 문자열일 수 없습니다.")
        self.messages.append(
            ConversationMessage(role=role, content=normalized)
        )
        if role == MessageRole.USER:
            self.turn_count += 1
        self.touch()

    def attach_document(self, document: UploadedDocument) -> bool:
        """문서를 중복 없이 상담 상태에 연결한다."""

        if document.conversation_id != self.conversation_id:
            raise ValueError(
                "첨부 문서의 conversation_id가 상담 상태와 다릅니다."
            )

        if any(
            item.document_id == document.document_id
            for item in self.documents
        ):
            return False

        self.documents.append(document.as_conversation_reference())
        self.touch()
        return True

    def update_document(self, document: UploadedDocument) -> None:
        """같은 document_id의 최신 처리 메타데이터로 교체한다."""

        if document.conversation_id != self.conversation_id:
            raise ValueError(
                "갱신 문서의 conversation_id가 상담 상태와 다릅니다."
            )

        for index, current in enumerate(self.documents):
            if current.document_id == document.document_id:
                self.documents[index] = document.as_conversation_reference()
                self.touch()
                return

        raise ValueError(
            f"상담에 연결되지 않은 document_id입니다: {document.document_id}"
        )

    def remove_document(self, document_id: str) -> UploadedDocument:
        """상담에 연결된 문서를 제거하고 제거한 메타데이터를 반환한다."""

        normalized = document_id.strip()
        if not normalized:
            raise ValueError("document_id는 빈 문자열일 수 없습니다.")

        for index, document in enumerate(self.documents):
            if document.document_id == normalized:
                removed = self.documents.pop(index)
                self.touch()
                return removed

        raise ValueError(f"상담에 연결되지 않은 document_id입니다: {normalized}")

    def confirmed_facts(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}

        for issue_id, slots in self.issue_slots.items():
            confirmed = {
                key: slot.value
                for key, slot in slots.items()
                if slot.status == SlotStatus.CONFIRMED
            }

            if confirmed:
                result[issue_id] = confirmed

        return result

    def missing_slots(self) -> list[tuple[str, SlotState]]:
        missing: list[tuple[str, SlotState]] = []

        for issue_id in self.all_issue_ids:
            for slot in self.issue_slots.get(issue_id, {}).values():
                if slot.is_missing():
                    missing.append((issue_id, slot))

        return sorted(
            missing,
            key=lambda item: (
                item[1].status != SlotStatus.CONFLICT,
                not item[1].risk_critical,
                item[1].priority,
                item[0],
                item[1].key,
            ),
        )


def build_issue_slots(issue_id: str) -> dict[str, SlotState]:
    issue = get_issue_definition(issue_id)

    return {
        definition.key: SlotState(
            key=definition.key,
            label=definition.label,
            question=definition.question,
            priority=definition.priority,
            risk_critical=definition.risk_critical,
        )
        for definition in issue.slots
    }


def add_issue_to_state(
    state: ConversationState,
    issue_id: str,
    *,
    as_related: bool = True,
) -> None:
    """기존 상담에 새 issue 슬롯을 중복 없이 추가한다."""

    get_issue_definition(issue_id)

    if issue_id in state.all_issue_ids:
        return

    if as_related:
        state.related_issue_ids.append(issue_id)
    else:
        old_primary = state.primary_issue_id
        state.primary_issue_id = issue_id
        if old_primary not in state.related_issue_ids:
            state.related_issue_ids.insert(0, old_primary)

    state.issue_slots[issue_id] = build_issue_slots(issue_id)
    state.touch()


def create_conversation_state(
    primary_issue_id: str,
    related_issue_ids: list[str] | None = None,
) -> ConversationState:
    """선택한 issue의 모든 슬롯을 unknown 상태로 만든다."""

    related = list(related_issue_ids or [])
    issue_ids = [primary_issue_id, *related]
    issue_slots = {
        issue_id: build_issue_slots(issue_id)
        for issue_id in issue_ids
    }

    return ConversationState(
        primary_issue_id=primary_issue_id,
        related_issue_ids=related,
        issue_slots=issue_slots,
    )
