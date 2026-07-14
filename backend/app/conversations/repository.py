"""
대화 이력 저장/조회.

save_message()는 user가 None(비로그인)이면 아무것도 하지 않습니다(no-op).
파트별 라우터는 저장 여부를 직접 신경 쓸 필요 없이 이 함수만 호출하면 됩니다.

get_session_state()/update_session_state()는 conversations.state(JSONB)를 다룹니다.
파트 무관 공용 함수이므로 dict만 주고받으며, 파트별 타입 캐스팅/검증은 호출부 책임입니다
(예: d파트는 app.graph.parts.d_part.schemas.DPartSessionState로 model_validate/model_dump).
"""
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.conversations.errors import ConversationNotFoundError
from app.conversations.models import Conversation as ConversationSchema, Message as MessageSchema
from app.conversations.orm import Conversation, Message
from app.core.db import SessionLocal


def _require_owned(db: Session, conversation_id: int, user_id: int) -> Conversation:
    """conversation_id가 user_id 소유일 때만 행을 돌려준다. 아니면 ConversationNotFoundError.

    소유권 검증(IDOR 방어)의 단일 지점 — 조회/수정 함수는 모두 이 게이트를 통과한다.
    """
    conversation = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id, Conversation.user_id == user_id)
        .first()
    )
    if conversation is None:
        raise ConversationNotFoundError(conversation_id)
    return conversation


async def create_conversation(user_id: int, part: str) -> ConversationSchema:
    db = SessionLocal()
    try:
        conversation = Conversation(user_id=user_id, part=part)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return ConversationSchema.model_validate(conversation, from_attributes=True)
    finally:
        db.close()


async def save_message(user_id: int | None, part: str, role: str, content: str, conversation_id: int):
    if user_id is None:
        return  # 비로그인 사용자는 저장하지 않음
    db = SessionLocal()
    try:
        _require_owned(db, conversation_id, user_id)  # 타인 대화방에 메시지 이어쓰기 차단
        db.add(Message(conversation_id=conversation_id, role=role, content=content))
        db.query(Conversation).filter(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        ).update({"updated_at": func.now()})
        db.commit()
    finally:
        db.close()


async def list_conversations(user_id: int) -> list[ConversationSchema]:
    db = SessionLocal()
    try:
        rows = (
            db.query(Conversation)
            .filter(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .all()
        )
        return [ConversationSchema.model_validate(row, from_attributes=True) for row in rows]
    finally:
        db.close()


async def load_conversation(conversation_id: int, user_id: int) -> list[MessageSchema]:
    """소유자가 아니거나 없으면 ConversationNotFoundError. 소유자면 메시지를 시간순으로."""
    db = SessionLocal()
    try:
        _require_owned(db, conversation_id, user_id)
        rows = (
            db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .all()
        )
        return [MessageSchema.model_validate(row, from_attributes=True) for row in rows]
    finally:
        db.close()


async def get_session_state(conversation_id: int, user_id: int) -> dict[str, Any] | None:
    """conversations.state 원본을 로드합니다(JSONB → dict). state가 NULL이면 None.

    소유자가 아니거나 대화방이 없으면 ConversationNotFoundError(과거처럼 None 아님) —
    호출부가 이 경로에서 404를 내야 존재 여부가 새지 않는다.
    """
    db = SessionLocal()
    try:
        conversation = _require_owned(db, conversation_id, user_id)
        return conversation.state
    finally:
        db.close()


async def update_conversation_title(conversation_id: int, user_id: int, title: str) -> None:
    """conversations.title만 갱신합니다. updated_at은 건드리지 않음(목록 정렬은 활동 시각 기준 유지)."""
    db = SessionLocal()
    try:
        _require_owned(db, conversation_id, user_id)
        db.query(Conversation).filter(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        ).update({"title": title})
        db.commit()
    finally:
        db.close()


async def update_session_state(conversation_id: int, user_id: int, state: dict[str, Any]) -> None:
    """conversations.state를 통째로 덮어씁니다(부분 병합 아님). 호출부가 전체 상태를 넘겨야 합니다.

    소유자가 아니거나 대화방이 없으면 ConversationNotFoundError.
    """
    db = SessionLocal()
    try:
        conversation = _require_owned(db, conversation_id, user_id)
        conversation.state = state
        db.commit()
    finally:
        db.close()
