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
async def test_call_structured_strips_markdown_code_fence(monkeypatch):
    """GPT-4o가 실제로 ```json ... ``` 코드펜스로 감싸서 응답하는 경우가 있음(라이브 확인, 2026-07-11)."""

    async def _fake_call_llm(prompt: str) -> str:
        return '```json\n{"stage": "전"}\n```'

    monkeypatch.setattr(d_part, "_call_llm", _fake_call_llm)

    result = await d_part.call_stage_router("계약하려고 준비 중이에요")

    assert result == {"stage": "전"}


def _tool_call_response(arguments: dict):
    call = SimpleNamespace(function=SimpleNamespace(arguments=json.dumps(arguments, ensure_ascii=False)))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])


@pytest.mark.asyncio
async def test_call_confirmation_returns_tool_answer_and_uses_cheaper_model(monkeypatch):
    captured = {}

    async def _fake_create(**kwargs):
        captured.update(kwargs)
        return _tool_call_response({"answer": "unclear", "reason": "조건부 긍정"})

    monkeypatch.setattr(d_part._client.chat.completions, "create", _fake_create)

    result = await d_part.call_confirmation("'전' 단계로 보입니다. 맞으신가요?", "맞긴 한데 좀 애매해요")

    assert result["answer"] == "unclear"
    # 3-way 판별에 gpt-4o를 쓸 이유가 없다 — 매 턴 호출되는 경로라 더 싼 모델로 고정
    assert captured["model"] == d_part.CONFIRMATION_MODEL
    assert captured["model"] != d_part.MODEL
    # enum으로 세 값 밖을 못 나가도록 tool calling을 강제한다
    assert captured["tools"][0]["function"]["parameters"]["properties"]["answer"]["enum"] == [
        "yes",
        "no",
        "unclear",
    ]


@pytest.mark.asyncio
async def test_call_supervisor_still_uses_default_model(monkeypatch):
    """_call_tool에 model 파라미터를 추가하면서 기존 호출부가 영향받지 않았는지."""
    captured = {}

    async def _fake_create(**kwargs):
        captured.update(kwargs)
        return _tool_call_response({"category": "open_qa"})

    monkeypatch.setattr(d_part._client.chat.completions, "create", _fake_create)

    await d_part.call_supervisor("보증금 반환청구 소송은 어떻게 하나요")

    assert captured["model"] == d_part.MODEL


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
