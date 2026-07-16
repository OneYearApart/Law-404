"""
maybe_summarize_conversation 임계값(threshold) 로직 테스트.
실제 Ollama 호출 없이 summarize_conversation을 monkeypatch — 트리거 여부만 검증한다.
docker의 law404_db를 그대로 사용(mock 없음) — 테스트 종료 후 생성한 row는 정리한다.
"""
import pytest
import pytest_asyncio

from app.auth.orm import User
from app.conversations.orm import Conversation, Message
from app.conversations.repository import create_conversation, load_conversation, save_message
from app.conversations import summarizer
from app.core.db import SessionLocal


@pytest_asyncio.fixture
async def user_id():
    db = SessionLocal()
    user = User(username="test_summarizer_user", password_hash="x", nickname="test_summarizer_nick")
    db.add(user)
    db.commit()
    db.refresh(user)
    uid = user.id
    db.close()

    yield uid

    db = SessionLocal()
    conv_ids = [c.id for c in db.query(Conversation).filter(Conversation.user_id == uid).all()]
    db.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
    db.query(Conversation).filter(Conversation.user_id == uid).delete(synchronize_session=False)
    db.query(User).filter(User.id == uid).delete()
    db.commit()
    db.close()


@pytest.mark.asyncio
async def test_maybe_summarize_skips_when_below_threshold(user_id, monkeypatch):
    called = False

    async def fake_summarize(messages):
        nonlocal called
        called = True
        return "제목"

    monkeypatch.setattr(summarizer, "summarize_conversation", fake_summarize)

    conversation = await create_conversation(user_id, "d")
    await save_message(user_id, "d", "user", "메시지1", conversation.id)
    await save_message(user_id, "d", "assistant", "메시지2", conversation.id)

    await summarizer.maybe_summarize_conversation(conversation.id, user_id, turn_threshold=4)

    assert called is False


@pytest.mark.asyncio
async def test_maybe_summarize_triggers_and_saves_title_at_threshold(user_id, monkeypatch):
    async def fake_summarize(messages):
        assert len(messages) == 4
        return "요약된 제목"

    monkeypatch.setattr(summarizer, "summarize_conversation", fake_summarize)

    conversation = await create_conversation(user_id, "d")
    await save_message(user_id, "d", "user", "메시지1", conversation.id)
    await save_message(user_id, "d", "assistant", "메시지2", conversation.id)
    await save_message(user_id, "d", "user", "메시지3", conversation.id)
    await save_message(user_id, "d", "assistant", "메시지4", conversation.id)

    await summarizer.maybe_summarize_conversation(conversation.id, user_id, turn_threshold=2)

    db = SessionLocal()
    title = db.query(Conversation).filter(Conversation.id == conversation.id).first().title
    db.close()
    assert title == "요약된 제목"


@pytest.mark.asyncio
async def test_maybe_summarize_leaves_title_unchanged_on_failure(user_id, monkeypatch):
    async def failing_summarize(messages):
        raise RuntimeError("ollama unreachable")

    monkeypatch.setattr(summarizer, "summarize_conversation", failing_summarize)

    conversation = await create_conversation(user_id, "d")
    await save_message(user_id, "d", "user", "메시지1", conversation.id)
    await save_message(user_id, "d", "assistant", "메시지2", conversation.id)

    await summarizer.maybe_summarize_conversation(conversation.id, user_id, turn_threshold=1)

    db = SessionLocal()
    title = db.query(Conversation).filter(Conversation.id == conversation.id).first().title
    db.close()
    assert title is None
