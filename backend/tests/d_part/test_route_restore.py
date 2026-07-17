"""
사이드바 재열람용 복원 경로 테스트.

D는 messages(평문)와 별개로, 완성 답변을 conversations.state의 turn_history에 구조 그대로
쌓는다. 사이드바에서 대화를 다시 열면 그 스냅샷으로 라이브 턴과 동일한 카드(판정·인용·용어)를
복원한다(A파트의 state 기반 복원과 같은 방식). 여기서는 (1) 턴마다 스냅샷이 append되는지,
(2) GET /chat/d/conversations/{id}가 그 상태를 돌려주는지를 확인한다.

get_current_user는 override, DB/그래프는 monkeypatch로 흉내(네트워크·DB 접근 없음).
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.routes import d_part as d_part_route
from app.auth.dependencies import get_current_user
from app.graph.parts.d_part.schemas import VictimJudgment
from app.main import app


@pytest.fixture(autouse=True)
def _override_auth():
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1)
    yield
    app.dependency_overrides.clear()


async def _one_chunk():
    yield "답변 본문"


def _stub_route(monkeypatch, final_state: dict, saved_states: list, prior_state=None):
    """update_session_state에 넘어가는 저장 상태(dict)를 saved_states에 캡처한다."""
    async def _fake_load_glossary():
        return []

    async def _fake_get_session_state(conversation_id, user_id):
        return prior_state  # None이면 fresh 세션

    async def _noop(*args, **kwargs):
        return None

    async def _capture_update(conversation_id, user_id, state_dict):
        saved_states.append(state_dict)

    class _Graph:
        async def ainvoke(self, *args, **kwargs):
            return {"response_stream": _one_chunk(), **final_state}

    monkeypatch.setattr(d_part_route._retriever, "load_glossary", _fake_load_glossary)
    monkeypatch.setattr(d_part_route, "get_session_state", _fake_get_session_state)
    monkeypatch.setattr(d_part_route, "save_message", _noop)
    monkeypatch.setattr(d_part_route, "update_session_state", _capture_update)
    monkeypatch.setattr(d_part_route, "maybe_summarize_conversation", _noop)
    monkeypatch.setattr(d_part_route, "d_graph", _Graph())


def _post():
    with TestClient(app) as client:
        client.post("/chat/d/", json={"conversation_id": 1, "user_input": "안녕"})


def test_turn_snapshot_is_appended_with_structured_fields(monkeypatch):
    """완성 답변 1턴이 turn_history에 구조 그대로(본문·판정·대응·성격) 쌓인다."""
    saved_states: list[dict] = []
    _stub_route(monkeypatch, {
        "victim_judgment": VictimJudgment.HIGH,
        "needs_response_assembly": True,
        "answer_kind": "judgment",
        "appendix_text": "■ 지금 확인·실행하실 점",
        "disclaimer_text": "본 안내는 일반적인 법률 정보이며",
    }, saved_states=saved_states)

    _post()

    assert saved_states, "update_session_state가 호출되지 않았다"
    history = saved_states[-1]["turn_history"]
    assert len(history) == 1
    snapshot = history[0]
    assert snapshot["user_input"] == "안녕"
    assert snapshot["text"] == "답변 본문"
    assert snapshot["judgment"] == "높음"
    assert snapshot["answer_kind"] == "judgment"
    assert snapshot["appendix"] == "■ 지금 확인·실행하실 점"
    assert snapshot["disclaimer"] == "본 안내는 일반적인 법률 정보이며"


def test_snapshot_appends_to_prior_history(monkeypatch):
    """이전 턴 이력 위에 이어붙는다 — reflective 재구성이 turn_history를 리셋하지 않는지 확인."""
    saved_states: list[dict] = []
    prior = {
        "turn_history": [
            {"user_input": "이전 질문", "text": "이전 답변", "citations": [],
             "judgment": None, "appendix": "", "disclaimer": "", "terms": [], "answer_kind": None}
        ]
    }
    _stub_route(monkeypatch, {"answer_kind": "open_qa"}, saved_states=saved_states, prior_state=prior)

    _post()

    history = saved_states[-1]["turn_history"]
    assert len(history) == 2
    assert history[0]["user_input"] == "이전 질문"
    assert history[1]["user_input"] == "안녕"


def test_get_d_conversation_returns_state_with_history(monkeypatch):
    """GET /chat/d/conversations/{id}는 복원용 상태(turn_history 포함)를 돌려준다."""
    stored = {
        "turn_history": [
            {"user_input": "질문", "text": "본문", "citations": [{"label": "제3조"}],
             "judgment": "있음", "appendix": "대응", "disclaimer": "면책",
             "terms": [{"term": "대항력", "description": "설명"}], "answer_kind": "scenario"}
        ]
    }

    async def _fake_get_session_state(conversation_id, user_id):
        return stored

    monkeypatch.setattr(d_part_route, "get_session_state", _fake_get_session_state)

    with TestClient(app) as client:
        response = client.get("/chat/d/conversations/1")

    assert response.status_code == 200
    history = response.json()["turn_history"]
    assert len(history) == 1
    assert history[0]["judgment"] == "있음"
    assert history[0]["answer_kind"] == "scenario"
    assert history[0]["citations"] == [{"label": "제3조"}]
