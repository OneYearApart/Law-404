"""
app/llm/d_part.py 프롬프트 조립 + JSON 파싱 테스트.
call_llm_stream_raw(base.py, 미구현 스텁)는 monkeypatch로 흉내내고, DB 접근 없음.
"""
import json

import pytest

from app.llm import d_part


def _make_fake_stream(payload: dict):
    text = json.dumps(payload, ensure_ascii=False)

    async def _fake(prompt: str):
        for i in range(0, len(text), 5):
            yield text[i : i + 5]

    return _fake


@pytest.mark.asyncio
async def test_call_stage_router_parses_json(monkeypatch):
    monkeypatch.setattr(d_part, "call_llm_stream_raw", _make_fake_stream({"stage": "전"}))

    result = await d_part.call_stage_router("계약하려고 준비 중이에요")

    assert result == {"stage": "전"}


@pytest.mark.asyncio
async def test_call_risk_trigger_parses_json(monkeypatch):
    payload = {"matched": True, "condition_no": 2, "reason": "보증금을 못 돌려받고 있다고 함"}
    monkeypatch.setattr(d_part, "call_llm_stream_raw", _make_fake_stream(payload))

    result = await d_part.call_risk_trigger("보증금을 못 돌려받고 있어요")

    assert result == payload


@pytest.mark.asyncio
async def test_call_victim_check_includes_existing_slots_in_prompt(monkeypatch):
    captured = {}

    async def _fake(prompt: str):
        captured["prompt"] = prompt
        payload = {
            "moved_in_and_fixed_date": "filled",
            "deposit_under_limit": "unclear",
            "multiple_victims": "unclear",
            "no_intent_to_return": "unclear",
            "multiple_victims_reason": None,
        }
        yield json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(d_part, "call_llm_stream_raw", _fake)
    existing = {"moved_in_and_fixed_date": "unclear"}

    result = await d_part.call_victim_check("전입신고 했어요", existing_slots=existing)

    assert result["moved_in_and_fixed_date"] == "filled"
    assert "existing_slots" in captured["prompt"]
    assert "moved_in_and_fixed_date" in captured["prompt"]


@pytest.mark.asyncio
async def test_call_special_cases_null_category(monkeypatch):
    monkeypatch.setattr(d_part, "call_llm_stream_raw", _make_fake_stream({"category": None}))

    result = await d_part.call_special_cases("전세 계약 갱신은 어떻게 하나요?")

    assert result == {"category": None}


def test_render_prompt_loads_template_and_appends_context():
    prompt = d_part._render_prompt("stage_router", user_input="테스트 발화")

    assert "계약 단계 판별" in prompt
    assert "테스트 발화" in prompt
