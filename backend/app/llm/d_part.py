"""
D파트 프롬프트 조립 + GPT-4o 호출.
d파트 담당자만 이 파일을 수정합니다.
프롬프트 내용/조립 방식은 graph/parts/d_part/prompts/*.md 를 참고합니다.

app/llm/base.py::call_llm_stream_raw는 아직 미구현 스텁이고 팀 공용 파일이라
건드리지 않기로 확정(2026-07-11) — 대신 이 파일에서 자체 OpenAI 클라이언트로
직접 GPT-4o를 호출한다. base.py를 쓰는 다른 파트 컨벤션과는 다른 방식이니
통합 시 팀에 공유할 것.

_call_llm은 스트리밍으로 받아 전체 텍스트로 모아 반환하고, 각 노드가 필요로 하는
구조화된 값(enum/슬롯 등)은 이 파일에서 그 텍스트를 JSON으로 파싱해 반환한다.
실제 enum/pydantic 모델로의 변환은 호출하는 노드 쪽 책임이다.
"""
import asyncio
import json
from pathlib import Path

from openai import APIError, AsyncOpenAI, RateLimitError

from app.core.config import settings

MODEL = "gpt-4o"
MAX_RETRIES = 3

_client = AsyncOpenAI(api_key=settings.openai_api_key)
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "graph" / "parts" / "d_part" / "prompts"


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


async def _call_structured(prompt_name: str, **kwargs) -> dict:
    prompt = _render_prompt(prompt_name, **kwargs)
    raw = await _call_llm(prompt)
    return json.loads(raw)


async def call_stage_router(user_input: str) -> dict:
    return await _call_structured("stage_router", user_input=user_input)


async def call_risk_trigger(user_input: str) -> dict:
    return await _call_structured("risk_trigger", user_input=user_input)


async def call_victim_check(user_input: str, existing_slots: dict) -> dict:
    return await _call_structured("victim_check", user_input=user_input, existing_slots=existing_slots)


async def call_special_cases(user_input: str) -> dict:
    return await _call_structured("special_cases", user_input=user_input)
