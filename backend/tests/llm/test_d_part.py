"""
app/llm/d_part.py 프롬프트 조립 + JSON 파싱 + 재시도 테스트.
실제 OpenAI 네트워크 호출은 monkeypatch로 흉내내고, DB 접근 없음.
"""

import json
from types import SimpleNamespace

import httpx
import pytest
from openai import APIError, BadRequestError, RateLimitError

from app.graph.parts.d_part.schemas import SlotStatus, VictimSlotExtraction
from app.llm import d_part


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code=429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def _make_chunk(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
    )


async def _fake_stream(contents: list[str]):
    for content in contents:
        yield _make_chunk(content)


async def _no_sleep(_seconds):
    return None


def _parsed_response(model):
    """chat.completions.parse가 돌려주는 응답 흉내 — .message.parsed에 pydantic 인스턴스가 온다."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(parsed=model, refusal=None),
            )
        ]
    )


@pytest.mark.asyncio
async def test_call_victim_check_includes_existing_slots_in_prompt(monkeypatch):
    captured = {}

    async def _fake_parse(**kwargs):
        captured.update(kwargs)
        return _parsed_response(
            VictimSlotExtraction(
                moved_in_and_fixed_date=SlotStatus.FILLED,
                deposit_under_limit=SlotStatus.UNCLEAR,
                multiple_victims=SlotStatus.UNCLEAR,
                no_intent_to_return=SlotStatus.UNCLEAR,
            )
        )

    monkeypatch.setattr(d_part._client.chat.completions, "parse", _fake_parse)
    existing = {"moved_in_and_fixed_date": "unclear"}

    result = await d_part.call_victim_check("전입신고 했어요", existing_slots=existing)

    assert result["moved_in_and_fixed_date"] == "filled"
    prompt = captured["messages"][0]["content"]
    assert "existing_slots" in prompt
    assert "moved_in_and_fixed_date" in prompt
    # 스키마를 API에 강제한다 — 응답 형태를 텍스트로 파싱하던 경로를 대체한 지점
    assert captured["response_format"] is VictimSlotExtraction


@pytest.mark.asyncio
async def test_call_victim_check_raises_when_parse_returns_nothing(monkeypatch):
    """거절이나 length 소진이면 .parsed가 None으로 온다. 예전 경로는 json.loads가 터졌지만
    이제는 무엇이 실패했는지 드러나는 예외로 끊는다."""

    async def _fake_parse(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(parsed=None, refusal=None),
                )
            ]
        )

    monkeypatch.setattr(d_part._client.chat.completions, "parse", _fake_parse)
    monkeypatch.setattr(d_part.asyncio, "sleep", _no_sleep)

    with pytest.raises(d_part.ToolCallMissing):
        await d_part.call_victim_check("전입신고 했어요", existing_slots={})


@pytest.mark.asyncio
async def test_query_expansion_strips_markdown_code_fence(monkeypatch):
    """모델이 실제로 코드펜스로 감싸서 응답하는 경우가 있음(라이브 확인, 2026-07-11).

    구조화 추출은 strict json_schema로 옮겨가 이 방어가 필요 없어졌지만, 확장 질의는 형태 없는
    산문이라 스키마를 씌울 수 없어 여전히 이 경로를 탄다. 방어가 살아있는 한 테스트도 남는다."""

    async def _fake_create(**kwargs):
        return _fake_stream(["```\n", "주택임대차보호법 대항력 우선변제권", "\n```"])

    monkeypatch.setattr(d_part._client.chat.completions, "create", _fake_create)

    result = await d_part.call_query_expansion("이사 나가도 보증금 받을 수 있나요")

    assert result == "주택임대차보호법 대항력 우선변제권"


def _tool_call_response(arguments: dict):
    call = SimpleNamespace(
        function=SimpleNamespace(arguments=json.dumps(arguments, ensure_ascii=False))
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))]
    )


@pytest.mark.asyncio
async def test_call_confirmation_returns_tool_answer_and_uses_cheaper_model(
    monkeypatch,
):
    captured = {}

    async def _fake_create(**kwargs):
        captured.update(kwargs)
        return _tool_call_response({"answer": "unclear", "reason": "조건부 긍정"})

    monkeypatch.setattr(d_part._client.chat.completions, "create", _fake_create)

    result = await d_part.call_confirmation(
        "'전' 단계로 보입니다. 맞으신가요?", "맞긴 한데 좀 애매해요"
    )

    assert result["answer"] == "unclear"
    # 3-way 판별에 gpt-4o를 쓸 이유가 없다 — 매 턴 호출되는 경로라 더 싼 모델로 고정
    assert captured["model"] == d_part.CONFIRMATION_MODEL
    assert captured["model"] != d_part.MODEL
    # enum으로 세 값 밖을 못 나가도록 tool calling을 강제한다
    assert captured["tools"][0]["function"]["parameters"]["properties"]["answer"][
        "enum"
    ] == [
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
    prompt = d_part._render_prompt("victim_check", user_input="테스트 발화")

    assert "미인지형 판별" in prompt
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


def _bad_request_error() -> BadRequestError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code=400, request=request)
    return BadRequestError("invalid schema", response=response, body=None)


@pytest.mark.asyncio
async def test_call_tool_raises_when_model_returns_no_tool_call(monkeypatch):
    """tool_choice로 강제했어도 length 소진·거절이면 tool call 없이 돌아온다.
    예전엔 tool_calls[0]을 곧바로 인덱싱해 TypeError/IndexError가 났는데, 그건 재시도 루프가
    잡는 예외가 아니라 재시도 없이 노드까지 올라갔다."""
    calls = {"count": 0}

    async def _fake_create(**kwargs):
        calls["count"] += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="length",
                    message=SimpleNamespace(tool_calls=None, refusal=None),
                )
            ]
        )

    monkeypatch.setattr(d_part._client.chat.completions, "create", _fake_create)
    monkeypatch.setattr(d_part.asyncio, "sleep", _no_sleep)

    with pytest.raises(d_part.ToolCallMissing):
        await d_part.call_supervisor("발화")

    # 재시도 대상이다 — length는 재호출로 회복될 수 있다
    assert calls["count"] == d_part.MAX_RETRIES


@pytest.mark.asyncio
async def test_call_tool_does_not_retry_bad_request(monkeypatch):
    """400은 스키마가 잘못됐다는 뜻이라 재시도해도 같은 답이 온다. 걸러내지 않으면
    스키마 실수가 백오프 3회에 가려져 '느린 실패'로 위장된다."""
    calls = {"count": 0}

    async def _fake_create(**kwargs):
        calls["count"] += 1
        raise _bad_request_error()

    monkeypatch.setattr(d_part._client.chat.completions, "create", _fake_create)
    monkeypatch.setattr(d_part.asyncio, "sleep", _no_sleep)

    with pytest.raises(BadRequestError):
        await d_part.call_supervisor("발화")

    assert calls["count"] == 1
