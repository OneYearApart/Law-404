"""
create_conversation / save_message / list_conversations / load_conversation 실제 DB 테스트.
docker의 law404_db를 그대로 사용 (mock 없음) — 테스트 종료 후 생성한 row는 정리한다.
"""
import pytest
import pytest_asyncio

from app.auth.orm import User
from app.conversations.errors import ConversationNotFoundError
from app.conversations.orm import Conversation, Message
from app.conversations.repository import (
    create_conversation,
    list_conversations,
    load_conversation,
    save_message,
)
from app.core.db import SessionLocal


@pytest_asyncio.fixture
async def user_id():
    db = SessionLocal()
    user = User(username="test_messages_user", password_hash="x", nickname="test_messages_nick")
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
async def test_create_conversation(user_id):
    conversation = await create_conversation(user_id, "d")
    assert conversation.user_id == user_id
    assert conversation.part == "d"


@pytest.mark.asyncio
async def test_save_message_then_load_conversation_returns_in_order(user_id):
    conversation = await create_conversation(user_id, "d")

    await save_message(user_id, "d", "user", "첫 번째 메시지", conversation.id)
    await save_message(user_id, "d", "assistant", "두 번째 메시지", conversation.id)

    messages = await load_conversation(conversation.id, user_id)

    assert [m.content for m in messages] == ["첫 번째 메시지", "두 번째 메시지"]
    assert [m.role for m in messages] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_save_message_noop_when_user_id_none(user_id):
    conversation = await create_conversation(user_id, "d")

    await save_message(None, "d", "user", "저장되면 안 됨", conversation.id)

    assert await load_conversation(conversation.id, user_id) == []


@pytest.mark.asyncio
async def test_save_message_to_non_owned_conversation_raises(user_id):
    """타인 소유 대화방에는 메시지를 이어쓰지 못한다(IDOR 쓰기 경로 차단)."""
    conversation = await create_conversation(user_id, "d")

    with pytest.raises(ConversationNotFoundError):
        await save_message(user_id + 12345, "d", "user", "몰래 이어쓰기", conversation.id)

    assert await load_conversation(conversation.id, user_id) == []


@pytest.mark.asyncio
async def test_load_conversation_by_non_owner_raises(user_id):
    conversation = await create_conversation(user_id, "d")
    await save_message(user_id, "d", "user", "내 메시지", conversation.id)

    with pytest.raises(ConversationNotFoundError):
        await load_conversation(conversation.id, user_id + 12345)


@pytest.mark.asyncio
async def test_list_conversations_returns_multiple_newest_first(user_id):
    first = await create_conversation(user_id, "d")
    second = await create_conversation(user_id, "d")
    assert first.id != second.id

    # first에 메시지를 저장해 updated_at을 second보다 최신으로 만든다
    await save_message(user_id, "d", "user", "다시 활성화", first.id)

    conversations = await list_conversations(user_id)
    ids = [c.id for c in conversations]

    assert first.id in ids and second.id in ids
    assert ids.index(first.id) < ids.index(second.id)


@pytest.mark.asyncio
async def test_list_conversations_titles_fall_back_to_first_question(user_id):
    """요약(title)이 붙기 전에도 사이드바가 빈 제목을 그리지 않아야 한다.
    폴백 재료인 첫 사용자 발화가 messages에 있어 클라이언트는 대신 못 채운다."""
    asked = await create_conversation(user_id, "d")
    untouched = await create_conversation(user_id, "d")
    await save_message(user_id, "d", "user", "보증금을 못 받고 있어요", asked.id)
    await save_message(user_id, "d", "assistant", "전입신고는 하셨나요?", asked.id)

    by_id = {c.id: c for c in await list_conversations(user_id)}

    assert by_id[asked.id].title == "보증금을 못 받고 있어요"   # assistant 발화가 아니라 첫 user 발화
    assert by_id[untouched.id].title == "새 상담"               # 질문 전이라 폴백 문구


@pytest.mark.asyncio
async def test_list_conversations_exposes_part_for_client_side_filtering(user_id):
    """목록은 전 파트를 반환하고 part를 함께 실어 클라이언트가 골라 쓴다."""
    d_conversation = await create_conversation(user_id, "d")
    a_conversation = await create_conversation(user_id, "a")

    parts = {c.id: c.part for c in await list_conversations(user_id)}

    assert parts[d_conversation.id] == "d"
    assert parts[a_conversation.id] == "a"
