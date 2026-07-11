"""
D파트 프롬프트 조립 + GPT-4o 호출.
d파트 담당자만 이 파일을 수정합니다.
프롬프트 내용/조립 방식은 graph/parts/d_part/prompts/*.md 를 참고합니다.

call_llm_stream_raw는 텍스트 스트림만 반환하므로, 각 노드가 필요로 하는
구조화된 값(enum/슬롯 등)은 이 파일에서 스트림 전체를 모아 JSON으로 파싱해 반환한다.
실제 enum/pydantic 모델로의 변환은 호출하는 노드 쪽 책임이다.
"""
import json
from pathlib import Path

from app.llm.base import call_llm_stream_raw

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "graph" / "parts" / "d_part" / "prompts"


def _render_prompt(prompt_name: str, **kwargs) -> str:
    template = (_PROMPTS_DIR / f"{prompt_name}.md").read_text(encoding="utf-8")
    context_lines = "\n".join(f"{key}: {value}" for key, value in kwargs.items())
    return f"{template}\n\n---\n\n{context_lines}"


async def _call_structured(prompt_name: str, **kwargs) -> dict:
    prompt = _render_prompt(prompt_name, **kwargs)
    chunks = [chunk async for chunk in call_llm_stream_raw(prompt)]
    return json.loads("".join(chunks))


async def call_stage_router(user_input: str) -> dict:
    return await _call_structured("stage_router", user_input=user_input)


async def call_risk_trigger(user_input: str) -> dict:
    return await _call_structured("risk_trigger", user_input=user_input)


async def call_victim_check(user_input: str, existing_slots: dict) -> dict:
    return await _call_structured("victim_check", user_input=user_input, existing_slots=existing_slots)


async def call_special_cases(user_input: str) -> dict:
    return await _call_structured("special_cases", user_input=user_input)
