"""
META 이벤트의 judgment 게이트 라우트 테스트.

victim_judgment는 carryover(DPartSessionState)라 판정이 한 번 확정되면 이후 턴에도 상태에
남는다. 그대로 내보내면 판정 이후 모든 답변에 배지가 재부착되므로, "이번 턴에 새로
확정했는지"를 뜻하는 needs_response_assembly로 게이트한다(action_plan/response_assembly와
동일 게이트).

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


def _stub_route(monkeypatch, final_state: dict, saved: list | None = None):
    async def _fake_get_session_state(conversation_id, user_id):
        return None

    async def _noop(*args, **kwargs):
        return None

    async def _capture_save(user_id, part, role, text, conversation_id):
        if saved is not None and role == "assistant":
            saved.append(text)

    class _Graph:
        async def ainvoke(self, *args, **kwargs):
            return {"response_stream": _one_chunk(), **final_state}

    monkeypatch.setattr(d_part_route, "get_session_state", _fake_get_session_state)
    monkeypatch.setattr(d_part_route, "save_message", _capture_save if saved is not None else _noop)
    monkeypatch.setattr(d_part_route, "update_session_state", _noop)
    monkeypatch.setattr(d_part_route, "maybe_summarize_conversation", _noop)
    monkeypatch.setattr(d_part_route, "d_graph", _Graph())


def _post() -> str:
    with TestClient(app) as client:
        return client.post("/chat/d/", json={"conversation_id": 1, "user_input": "안녕"}).text


def test_fresh_judgment_is_emitted_in_meta(monkeypatch):
    _stub_route(monkeypatch, {
        "victim_judgment": VictimJudgment.HIGH,
        "needs_response_assembly": True,
    })

    body = _post()

    assert '"type":"meta"' in body
    assert "높음" in body


def test_carryover_judgment_without_fresh_assembly_is_not_emitted(monkeypatch):
    """판정이 확정된 다음 턴(단순 질의응답)에는 배지가 다시 붙으면 안 된다."""
    _stub_route(monkeypatch, {
        "victim_judgment": VictimJudgment.HIGH,  # 세션에 남아 있는 이전 턴 판정
        "needs_response_assembly": False,
    })

    body = _post()

    assert "높음" not in body
    assert '"type":"meta"' not in body


def test_slot_question_turn_has_no_meta(monkeypatch):
    """요건 질문만 던지는 턴은 판정도 근거도 없으므로 META 자체가 나가지 않는다."""
    _stub_route(monkeypatch, {})

    body = _post()

    assert '"type":"meta"' not in body
    assert '"type":"token"' in body


def test_appendix_and_disclaimer_are_structured_not_inlined(monkeypatch):
    """액션플랜·면책은 토큰 평문에 섞이지 않고 META로 나간다 — 프론트가 별도 블록으로 렌더한다."""
    _stub_route(monkeypatch, {
        "appendix_text": "■ 지금 확인·실행하실 점\n- 신청하실 수 있습니다.",
        "disclaimer_text": "본 안내는 일반적인 법률 정보이며",
    })

    body = _post()

    assert '"appendix"' in body
    assert '"disclaimer"' in body
    token_lines = [line for line in body.splitlines() if '"type":"token"' in line]
    assert token_lines and all("■" not in line for line in token_lines)


def test_saved_message_matches_what_user_sees(monkeypatch):
    """messages에 저장되는 텍스트는 사용자가 보는 것(본문+액션플랜+면책)과 같아야 이력이 일치한다.
    구조화해 내보낸 블록이 저장에서 누락되면 대화 이력이 반쪽이 된다."""
    saved: list[str] = []
    _stub_route(monkeypatch, {
        "appendix_text": "■ 지금 확인·실행하실 점\n- 신청하실 수 있습니다.",
        "disclaimer_text": "본 안내는 일반적인 법률 정보이며",
    }, saved=saved)

    _post()

    assert len(saved) == 1
    assert "답변 본문" in saved[0]
    assert "■ 지금 확인·실행하실 점" in saved[0]
    assert "본 안내는 일반적인 법률 정보이며" in saved[0]
