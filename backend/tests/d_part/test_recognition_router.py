"""
recognition_router 노드 테스트 (DB 접근 없는 순수 로직).
call_recognition_check(LLM 호출)는 monkeypatch로 흉내낸다.
"""
import pytest

from app.graph.parts.d_part.nodes import recognition_router
from app.graph.parts.d_part.nodes.recognition_router import route_recognition


@pytest.mark.asyncio
async def test_recognized_true(monkeypatch):
    async def _fake(user_input: str) -> dict:
        return {"recognized": True}

    monkeypatch.setattr(recognition_router.llm_d_part, "call_recognition_check", _fake)

    result = await route_recognition({"user_input": "이미 피해자로 인정받았어요"})

    assert result["recognized"] is True


@pytest.mark.asyncio
async def test_recognized_false(monkeypatch):
    async def _fake(user_input: str) -> dict:
        return {"recognized": False}

    monkeypatch.setattr(recognition_router.llm_d_part, "call_recognition_check", _fake)

    result = await route_recognition({"user_input": "보증금을 못 받고 있어요"})

    assert result["recognized"] is False


@pytest.mark.asyncio
async def test_uses_active_query_over_raw_user_input_when_present(monkeypatch):
    seen_input = {}

    async def _fake(user_input: str) -> dict:
        seen_input["value"] = user_input
        return {"recognized": True}

    monkeypatch.setattr(recognition_router.llm_d_part, "call_recognition_check", _fake)

    await route_recognition({"user_input": "네", "active_query": "이미 피해자로 인정받았어요"})

    assert seen_input["value"] == "이미 피해자로 인정받았어요"
