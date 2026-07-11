"""
대화 이력 저장/조회.

save_message()는 user가 None(비로그인)이면 아무것도 하지 않습니다(no-op).
파트별 라우터는 저장 여부를 직접 신경 쓸 필요 없이 이 함수만 호출하면 됩니다.

get_session_state()/update_session_state()는 conversations.state(JSONB)를 다룹니다.
파트 무관 공용 함수이므로 dict만 주고받으며, 파트별 타입 캐스팅/검증은 호출부 책임입니다
(예: d파트는 app.graph.parts.d_part.schemas.DPartSessionState로 model_validate/model_dump).
"""
from typing import Any

from app.conversations.orm import Conversation
from app.core.db import SessionLocal


async def save_message(user_id: int | None, part: str, role: str, content: str):
    if user_id is None:
        return  # 비로그인 사용자는 저장하지 않음
    raise NotImplementedError


async def list_conversations(user_id: int):
    raise NotImplementedError


async def load_conversation(conversation_id: int):
    raise NotImplementedError


async def get_session_state(conversation_id: int) -> dict[str, Any] | None:
    """conversations.state 원본을 로드합니다(JSONB → dict). 행이 없거나 state가 NULL이면 None."""
    db = SessionLocal()
    try:
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        return conversation.state if conversation is not None else None
    finally:
        db.close()


async def update_session_state(conversation_id: int, state: dict[str, Any]) -> None:
    """conversations.state를 통째로 덮어씁니다(부분 병합 아님). 호출부가 전체 상태를 넘겨야 합니다."""
    db = SessionLocal()
    try:
        conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if conversation is None:
            raise ValueError(f"conversation {conversation_id} not found")
        conversation.state = state
        db.commit()
    finally:
        db.close()
