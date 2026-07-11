"""
app/llm/d_part.py 프롬프트 조립 + JSON 파싱 + 재시도 테스트.
실제 OpenAI 네트워크 호출은 monkeypatch로 흉내내고, DB 접근 없음.
"""
import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIError, RateLimitError

from app.llm import d_part


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code=429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def _make_chunk(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])


async def _fake_stream(contents: list[str]):
    for content in contents:
        yield _make_chunk(content)


async def _no_sleep(_seconds):
    return None


@pytest.mark.asyncio
async def test_call_stage_router_parses_json(monkeypatch):
    async def _fake_call_llm(prompt: str) -> str:
        return json.dumps({"stage": "전"}, ensure_ascii=False)

    monkeypatch.setattr(d_part, "_call_llm", _fake_call_llm)

    result = await d_part.call_stage_router("계약하려고 준비 중이에요")

    assert result == {"stage": "전"}


@pytest.mark.asyncio
async def test_call_risk_trigger_parses_json(monkeypatch):
    payload = {"matched": True, "condition_no": 2, "reason": "보증금을 못 돌려받고 있다고 함"}

    async def _fake_call_llm(prompt: str) -> str:
        return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(d_part, "_call_llm", _fake_call_llm)

    result = await d_part.call_risk_trigger("보증금을 못 돌려받고 있어요")

    assert result == payload


@pytest.mark.asyncio
async def test_call_victim_check_includes_existing_slots_in_prompt(monkeypatch):
    captured = {}

    async def _fake_call_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        payload = {
            "moved_in_and_fixed_date": "filled",
            "deposit_under_limit": "unclear",
            "multiple_victims": "unclear",
            "no_intent_to_return": "unclear",
            "multiple_victims_reason": None,
        }
        return json.dumps(payload, ensure_ascii=False)

    monkeypatch.setattr(d_part, "_call_llm", _fake_call_llm)
    existing = {"moved_in_and_fixed_date": "unclear"}

    result = await d_part.call_victim_check("전입신고 했어요", existing_slots=existing)

    assert result["moved_in_and_fixed_date"] == "filled"
    assert "existing_slots" in captured["prompt"]
    assert "moved_in_and_fixed_date" in captured["prompt"]


@pytest.mark.asyncio
async def test_call_special_cases_null_category(monkeypatch):
    async def _fake_call_llm(prompt: str) -> str:
        return json.dumps({"category": None})

    monkeypatch.setattr(d_part, "_call_llm", _fake_call_llm)

    result = await d_part.call_special_cases("전세 계약 갱신은 어떻게 하나요?")

    assert result == {"category": None}


@pytest.mark.asyncio
async def test_call_structured_strips_markdown_code_fence(monkeypatch):
    """GPT-4o가 실제로 ```json ... ``` 코드펜스로 감싸서 응답하는 경우가 있음(라이브 확인, 2026-07-11)."""

    async def _fake_call_llm(prompt: str) -> str:
        return '```json\n{"stage": "전"}\n```'

    monkeypatch.setattr(d_part, "_call_llm", _fake_call_llm)

    result = await d_part.call_stage_router("계약하려고 준비 중이에요")

    assert result == {"stage": "전"}


def test_render_prompt_loads_template_and_appends_context():
    prompt = d_part._render_prompt("stage_router", user_input="테스트 발화")

    assert "계약 단계 판별" in prompt
    assert "테스트 발화" in prompt


@pytest.mark.asyncio
async def test_call_llm_succeeds_on_first_try(monkeypatch):
    async def _fake_create(**kwargs):
        return _fake_stream(["안", "녕"])

    monkeypatch.setattr(d_part._client.chat.completions, "create", _fake_create)

    result = await d_part._call_llm("prompt")

    assert result == "안녕"


@pytest.mark.asyncio
async def test_call_llm_retries_after_rate_limit_then_succeeds(monkeypatch):
    calls = {"count": 0}

    async def _fake_create(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise _rate_limit_error()
        return _fake_stream(["ok"])

    monkeypatch.setattr(d_part._client.chat.completions, "create", _fake_create)
    monkeypatch.setattr(d_part.asyncio, "sleep", _no_sleep)

    result = await d_part._call_llm("prompt")

    assert result == "ok"
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_call_llm_raises_after_max_retries(monkeypatch):
    async def _fake_create(**kwargs):
        raise _rate_limit_error()

    monkeypatch.setattr(d_part._client.chat.completions, "create", _fake_create)
    monkeypatch.setattr(d_part.asyncio, "sleep", _no_sleep)

    with pytest.raises(RateLimitError):
        await d_part._call_llm("prompt")
