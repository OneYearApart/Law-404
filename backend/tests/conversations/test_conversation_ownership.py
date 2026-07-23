"""
단위 25 — conversation_id 소유권 검증(IDOR) 라우트 레벨 테스트.

로그인한 사용자 B가 사용자 A의 대화방을 조회/이어쓰기하려 하면 404가 나야 한다.
(403이 아니라 404 — 대화방 존재 여부 유출 방지)

get_current_user 의존성을 override해 JWT 발급 없이 A/B를 전환한다.
docker의 law404_db를 그대로 사용 — 생성한 row는 정리한다.
"""

from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.auth.orm import User
from app.conversations.orm import Conversation, Message
from app.core.db import SessionLocal
from app.main import app


@pytest_asyncio.fixture
async def two_users_one_conversation():
    """A(대화방+메시지 소유), B(무관). (conv_id, a_id, b_id)를 돌려준다."""
    db = SessionLocal()
    a = User(username="idor_owner", password_hash="x", nickname="owner")
    b = User(username="idor_attacker", password_hash="x", nickname="attacker")
    db.add_all([a, b])
    db.flush()
    conv = Conversation(user_id=a.id, part="d")
    db.add(conv)
    db.flush()
    db.add(Message(conversation_id=conv.id, role="user", content="보증금 3억"))
    db.commit()
    conv_id, a_id, b_id = conv.id, a.id, b.id
    db.close()

    yield conv_id, a_id, b_id

    db = SessionLocal()
    db.query(Message).filter(Message.conversation_id == conv_id).delete(
        synchronize_session=False
    )
    db.query(Conversation).filter(Conversation.id == conv_id).delete()
    db.query(User).filter(User.id.in_([a_id, b_id])).delete(synchronize_session=False)
    db.commit()
    db.close()


def _login_as(user_id: int):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_get_conversation_by_non_owner_returns_404(two_users_one_conversation):
    conv_id, _a_id, b_id = two_users_one_conversation
    _login_as(b_id)

    with TestClient(app) as client:
        resp = client.get(f"/conversations/{conv_id}")

    assert resp.status_code == 404


def test_get_conversation_by_owner_returns_200(two_users_one_conversation):
    conv_id, a_id, _b_id = two_users_one_conversation
    _login_as(a_id)

    with TestClient(app) as client:
        resp = client.get(f"/conversations/{conv_id}")

    assert resp.status_code == 200
    assert [m["content"] for m in resp.json()] == ["보증금 3억"]


def test_chat_d_by_non_owner_returns_404_before_streaming(two_users_one_conversation):
    """타인 대화방으로 POST /chat/d/ → 소유권 검증이 그래프 실행 전에 404를 낸다."""
    conv_id, _a_id, b_id = two_users_one_conversation
    _login_as(b_id)

    with TestClient(app) as client:
        resp = client.post(
            "/chat/d/", json={"conversation_id": conv_id, "user_input": "안녕"}
        )

    assert resp.status_code == 404


def test_get_nonexistent_conversation_returns_404(two_users_one_conversation):
    _conv_id, a_id, _b_id = two_users_one_conversation
    _login_as(a_id)

    with TestClient(app) as client:
        resp = client.get("/conversations/-1")

    assert resp.status_code == 404
