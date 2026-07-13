"""
stage_router 노드 상태기계 테스트 (DB 접근 없는 순수 로직).
"""
import pytest

from app.graph.parts.d_part.nodes import stage_router
from app.graph.parts.d_part.nodes.stage_router import route_stage
from app.graph.parts.d_part.schemas import Stage


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
async def test_affirmative_confirmation_sets_confirmed_true():
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
async def test_negative_confirmation_resets_and_reasks():
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
