"""
D파트 프롬프트 조립 + GPT-4o 호출.
d파트 담당자만 이 파일을 수정합니다.
프롬프트 내용/조립 방식은 graph/parts/d_part/prompts/*.md 를 참고합니다.
"""
from app.llm.base import call_llm_stream_raw


async def call_prompt(prompt_name: str, **kwargs):
    # TODO: graph/parts/d_part/prompts/{prompt_name}.md 로드 후 kwargs로 포맷
    prompt = ""
    async for chunk in call_llm_stream_raw(prompt):
        yield chunk


async def call_victim_check(user_input: str):
    async for chunk in call_prompt("victim_check", user_input=user_input):
        yield chunk


async def call_risk_trigger(user_input: str):
    async for chunk in call_prompt("risk_trigger", user_input=user_input):
        yield chunk
