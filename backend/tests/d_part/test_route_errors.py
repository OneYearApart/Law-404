"""
단위 31 — SSE 에러 이벤트 + 요청 바디 타입 라우트 테스트.

- 그래프가 예외를 던져도 스트림이 조용히 끊기지 않고 error 이벤트로 정상 종료한다.
- conversation_id 누락 요청은 500이 아니라 422(요청 검증 실패).

get_current_user는 override, DB/그래프는 monkeypatch로 흉내(네트워크·DB 접근 없음).
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.routes import d_part as d_part_route
from app.auth.dependencies import get_current_user
from app.main import app


@pytest.fixture(autouse=True)
def _override_auth():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    yield
    app.dependency_overrides.clear()


def test_missing_conversation_id_returns_422():
    with TestClient(app) as client:
        resp = client.post(
            "/chat/d/", json={"user_input": "안녕"}
        )  # conversation_id 없음
    assert resp.status_code == 422


def test_graph_exception_emits_error_event_and_ends_stream(monkeypatch):
    async def _fake_get_session_state(conversation_id, user_id):
        return None  # 소유권 통과(스트리밍 전 단계) + DB 우회

    async def _noop_save(*args, **kwargs):
        return None

    class _BoomGraph:
        async def ainvoke(self, *args, **kwargs):
            raise RuntimeError("그래프 내부 폭발")

    monkeypatch.setattr(d_part_route, "get_session_state", _fake_get_session_state)
    monkeypatch.setattr(d_part_route, "save_message", _noop_save)
    monkeypatch.setattr(d_part_route, "d_graph", _BoomGraph())

    with TestClient(app) as client:
        resp = client.post(
            "/chat/d/", json={"conversation_id": 1, "user_input": "안녕"}
        )

    assert resp.status_code == 200  # 스트림은 200으로 시작됨(예외는 스트림 안에서 발생)
    body = resp.text
    assert '"type":"loading"' in body  # 스트림이 실제로 시작됐고
    assert '"type":"error"' in body  # 조용히 끊기지 않고 error 이벤트로 종료
    assert d_part_route._ERROR_MESSAGE in body
