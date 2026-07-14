"""
stage_router 노드 상태기계 테스트 (DB 접근 없는 순수 로직).
확인 응답 판별(parse_confirmation → LLM)은 monkeypatch로 흉내내고, 노드의 yes/no/unclear
상태 전이만 검증한다. 판별 자체의 정확도(과탐/미탐)는 mock으로는 검증할 수 없으므로
라이브 테스트(test_live_smoke.py)에서 실제 호출로 확인한다.
"""
import pytest

from app.graph.parts.d_part.nodes import stage_router
from app.graph.parts.d_part.nodes.stage_router import route_stage
from app.graph.parts.d_part.schemas import Stage


def _fake_confirmation(answer):
    async def _fake(question: str, user_input: str):
        return answer

    return _fake


@pytest.mark.asyncio
async def test_first_turn_classifies_and_asks_confirmation(monkeypatch):
    async def _fake_call_stage_router(user_input: str) -> dict:
        return {"stage": "중"}

    monkeypatch.setattr(stage_router.llm_d_part, "call_stage_router", _fake_call_stage_router)

    state = {"user_input": "지금 전세로 살고 있는데 문제가 생겼어요"}

    result = await route_stage(state)

    assert result["stage"] == Stage.DURING
    assert result["stage_confirmed"] is False
    assert result["final_answer"] is not None
    assert Stage.DURING.value in result["final_answer"]
    assert result["active_query"] == "지금 전세로 살고 있는데 문제가 생겼어요"


@pytest.mark.asyncio
async def test_affirmative_confirmation_sets_confirmed_true(monkeypatch):
    monkeypatch.setattr(stage_router, "parse_confirmation", _fake_confirmation(True))
    state = {
        "user_input": "네 맞아요",
        "stage": Stage.DURING,
        "stage_confirmed": False,
        "active_query": "지금 전세로 살고 있는데 문제가 생겼어요",
    }

    result = await route_stage(state)

    assert result["stage"] == Stage.DURING
    assert result["stage_confirmed"] is True
    assert result["final_answer"] is None
    # 핵심 버그 수정 지점: 확인 답변("네 맞아요")이 지난 턴에 스택해둔 실질 질문을 덮어쓰면 안 됨
    assert result["active_query"] == "지금 전세로 살고 있는데 문제가 생겼어요"


@pytest.mark.asyncio
async def test_negative_confirmation_resets_and_reasks(monkeypatch):
    monkeypatch.setattr(stage_router, "parse_confirmation", _fake_confirmation(False))
    state = {
        "user_input": "아니요 그건 아니에요",
        "stage": Stage.DURING,
        "stage_confirmed": False,
        "active_query": "지금 전세로 살고 있는데 문제가 생겼어요",
    }

    result = await route_stage(state)

    assert result["stage"] is None
    assert result["stage_confirmed"] is False
    assert result["final_answer"] is not None
    assert result["active_query"] is None


@pytest.mark.asyncio
async def test_unclear_confirmation_reasks_without_confirming(monkeypatch):
    """예/아니오로 확신할 수 없는 응답은 긍정으로 삼키지 말고 재질문해야 한다."""
    monkeypatch.setattr(stage_router, "parse_confirmation", _fake_confirmation(None))
    state = {
        "user_input": "맞긴 한데 좀 애매해요",
        "stage": Stage.DURING,
        "stage_confirmed": False,
        "active_query": "지금 전세로 살고 있는데 문제가 생겼어요",
    }

    result = await route_stage(state)

    assert result["stage_confirmed"] is False
    assert result["stage"] == Stage.DURING
    assert Stage.DURING.value in result["final_answer"]
    assert result["stage_confirm_attempts"] == 1
    assert result["active_query"] == "지금 전세로 살고 있는데 문제가 생겼어요"


@pytest.mark.asyncio
async def test_repeated_unclear_gives_up_and_passes_through(monkeypatch):
    """unclear가 반복돼도 무한 재질문에 갇히면 안 된다 — 상한 도달 시 판별값 그대로 통과."""
    monkeypatch.setattr(stage_router, "parse_confirmation", _fake_confirmation(None))
    state = {
        "user_input": "그건 왜 물어보세요?",
        "stage": Stage.DURING,
        "stage_confirmed": False,
        "active_query": "지금 전세로 살고 있는데 문제가 생겼어요",
    }

    for _ in range(stage_router._MAX_CONFIRM_ATTEMPTS):
        state.pop("final_answer", None)
        state = await route_stage(state)

    assert state["stage_confirmed"] is True
    assert state["final_answer"] is None
    # 확인은 포기하되 원래 실질 질문은 그대로 살아 있어야 한다
    assert state["active_query"] == "지금 전세로 살고 있는데 문제가 생겼어요"


@pytest.mark.asyncio
async def test_already_confirmed_state_passes_through_unchanged():
    state = {
        "user_input": "아무 말이나 해도 재판별되면 안 됨",
        "stage": Stage.PRE,
        "stage_confirmed": True,
    }

    result = await route_stage(state)

    assert result["stage"] == Stage.PRE
    assert result["stage_confirmed"] is True
    assert "final_answer" not in result or result["final_answer"] is None
    assert result["active_query"] == "아무 말이나 해도 재판별되면 안 됨"
