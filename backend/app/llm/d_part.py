"""
D파트 프롬프트 조립 + GPT-4o 호출.
d파트 담당자만 이 파일을 수정합니다.
프롬프트 내용/조립 방식은 graph/parts/d_part/prompts/*.md 를 참고합니다.

app/llm/base.py::call_llm_stream_raw는 아직 미구현 스텁이고 팀 공용 파일이라
건드리지 않기로 확정(2026-07-11) — 대신 이 파일에서 자체 OpenAI 클라이언트로
직접 GPT-4o를 호출한다. base.py를 쓰는 다른 파트 컨벤션과는 다른 방식이니
통합 시 팀에 공유할 것.

_call_llm은 스트리밍으로 받아 전체 텍스트로 모아 반환하고, 각 노드가 필요로 하는
구조화된 값(enum/슬롯 등)은 이 파일에서 그 텍스트를 JSON으로 파싱해 반환한다
(_call_structured). supervisor 분류처럼 카테고리를 스키마로 강제해야 하는 경우는
OpenAI tool calling을 쓰는 _call_tool을 대신 쓴다. 실제 enum/pydantic 모델로의
변환은 호출하는 노드 쪽 책임이다.
"""
import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator

from openai import APIError, AsyncOpenAI, RateLimitError

from app.core.config import settings
from app.graph.parts.d_part.schemas import GENERAL_TOPIC_LABELS, SPECIAL_CASE_CATEGORIES

MODEL = "gpt-4o"
MAX_RETRIES = 3

_client = AsyncOpenAI(api_key=settings.openai_api_key)
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "graph" / "parts" / "d_part" / "prompts"

# supervisor가 고를 수 있는 전체 카테고리 — victim_interview(위험신호+미인지형) +
# 특수상황 4종 + 일반시나리오 13종 + open_qa(어디에도 안 걸리는 질문). enum 값은
# schemas.py의 GENERAL_TOPIC_LABELS/SPECIAL_CASE_CATEGORIES와 그대로 맞물려야
# general_scenario.py/special_cases.py의 실행부가 같은 키로 조회할 수 있다.
_SUPERVISOR_CATEGORIES = [
    "victim_interview",
    *[f"special_case:{name}" for name in SPECIAL_CASE_CATEGORIES],
    *[f"general_topic:{key}" for key in GENERAL_TOPIC_LABELS],
    "open_qa",
]

_SUPERVISOR_TOOL = {
    "type": "function",
    "function": {
        "name": "route",
        "description": "사용자 발화를 카테고리 하나로 분류해 다음 처리 노드를 정한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": _SUPERVISOR_CATEGORIES},
                "reason": {"type": "string", "description": "판단 근거 한 줄"},
            },
            "required": ["category"],
        },
    },
}


def _render_prompt(prompt_name: str, **kwargs) -> str:
    template = (_PROMPTS_DIR / f"{prompt_name}.md").read_text(encoding="utf-8")
    context_lines = "\n".join(f"{key}: {value}" for key, value in kwargs.items())
    return f"{template}\n\n---\n\n{context_lines}"


async def _call_llm(prompt: str) -> str:
    for attempt in range(MAX_RETRIES):
        try:
            stream = await _client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            return "".join([event.choices[0].delta.content or "" async for event in stream])
        except (RateLimitError, APIError):
            if attempt == MAX_RETRIES - 1:
                raise
            await asyncio.sleep(2**attempt)


def _strip_code_fence(text: str) -> str:
    """GPT-4o가 JSON을 ```json ... ``` 코드펜스로 감싸서 반환하는 경우가 있어 벗겨낸다
    (실제 라이브 호출에서 확인된 동작 — monkeypatch 테스트는 순수 JSON 문자열만 흉내내
    이 문제를 못 잡았음, 2026-07-11)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text.removeprefix("```")
        text = text.removesuffix("```").strip()
    return text


async def _call_structured(prompt_name: str, **kwargs) -> dict:
    prompt = _render_prompt(prompt_name, **kwargs)
    raw = await _call_llm(prompt)
    return json.loads(_strip_code_fence(raw))


async def _call_tool(prompt_name: str, tool: dict, **kwargs) -> dict:
    """_call_structured와 달리 응답을 텍스트로 받아 JSON 파싱하지 않고, OpenAI tool
    calling으로 스키마(enum)를 강제해 모델이 정의된 카테고리 밖의 값을 반환할 수
    없게 한다. 스트리밍 대상이 아니라 stream=False로 호출한다."""
    prompt = _render_prompt(prompt_name, **kwargs)
    tool_name = tool["function"]["name"]
    for attempt in range(MAX_RETRIES):
        try:
            response = await _client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": tool_name}},
            )
            call = response.choices[0].message.tool_calls[0]
            return json.loads(call.function.arguments)
        except (RateLimitError, APIError):
            if attempt == MAX_RETRIES - 1:
                raise
            await asyncio.sleep(2**attempt)


async def call_stage_router(user_input: str) -> dict:
    return await _call_structured("stage_router", user_input=user_input)


async def call_victim_check(user_input: str, existing_slots: dict) -> dict:
    return await _call_structured("victim_check", user_input=user_input, existing_slots=existing_slots)


async def call_supervisor(user_input: str) -> dict:
    return await _call_tool("supervisor", _SUPERVISOR_TOOL, user_input=user_input)


async def generate_response(context: str) -> AsyncGenerator[str, None]:
    """최종 응답(원문→해설→상황적용) 진짜 토큰 스트리밍 — 다른 call_*와 달리 전체를 모아
    JSON 파싱하지 않고 그대로 흘려보낸다. 스트림 시작 후 실패하면 이미 클라이언트로
    청크가 나간 상태라 재시도하지 않고 그대로 전파한다."""
    prompt = _render_prompt("response", context=context)
    stream = await _client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )
    async for event in stream:
        content = event.choices[0].delta.content
        if content:
            yield content
