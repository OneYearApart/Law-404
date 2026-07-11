"""
get_session_state / update_session_state 실제 DB round-trip 테스트.
docker의 law404_db를 그대로 사용 (mock 없음) — 테스트 종료 후 생성한 row는 정리한다.
"""
import pytest
import pytest_asyncio

from app.auth.orm import User
from app.conversations.orm import Conversation
from app.conversations.repository import get_session_state, update_session_state
from app.core.db import SessionLocal


@pytest_asyncio.fixture
async def conversation_id():
    db = SessionLocal()
    user = User(username="test_session_state_user", password_hash="x", nickname="test_session_state_nick")
    db.add(user)
    db.flush()
    conversation = Conversation(user_id=user.id, part="d")
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    conv_id = conversation.id
    user_id = user.id
    db.close()

    yield conv_id

    db = SessionLocal()
    db.query(Conversation).filter(Conversation.id == conv_id).delete()
    db.query(User).filter(User.id == user_id).delete()
    db.commit()
    db.close()


@pytest.mark.asyncio
async def test_get_session_state_missing_conversation_returns_none():
    assert await get_session_state(-1) is None


@pytest.mark.asyncio
async def test_update_then_get_session_state_roundtrip(conversation_id):
    assert await get_session_state(conversation_id) is None

    state = {"stage": "pre", "victim_slots": {"multiple_victims_reason": "테스트"}}
    await update_session_state(conversation_id, state)

    assert await get_session_state(conversation_id) == state


@pytest.mark.asyncio
async def test_update_session_state_missing_conversation_raises():
    with pytest.raises(ValueError):
        await update_session_state(-1, {"stage": "pre"})
