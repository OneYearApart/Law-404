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
from app.graph.parts.d_part.schemas import (
    GENERAL_TOPIC_LABELS,
    RISK_SIGNALS,
    SPECIAL_CASE_CATEGORIES,
)

MODEL = "gpt-4o"
# 확인 응답 판별은 예/아니오/불명확 3-way 분류라 법률지식이 필요 없고 매 턴 호출되므로
# 더 싼 모델을 쓴다. 단위 21′에서 로컬모델(EXAONE)로 스왑 검토 예정.
CONFIRMATION_MODEL = "gpt-4o-mini"
MAX_RETRIES = 3

_client = AsyncOpenAI(api_key=settings.openai_api_key)
_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "graph" / "parts" / "d_part" / "prompts"

# supervisor는 카테고리 하나가 아니라 상황의 축을 각각 판별한다(SituationState). 예전엔 축들이
# 카테고리 enum 하나로 압축돼 있어 인지여부가 topic에 가려지는 등 축끼리 서로를 덮어썼다.
# enum 값은 schemas.py의 상수와 그대로 맞물려야 general_scenario.py/special_cases.py의 실행부가
# 같은 키로 조회할 수 있다.
#
# topic/special_case는 "해당 없음"이 정상값이라 required에 넣지 않는다 — JSON Schema의
# null 유니온은 비-strict tool calling에서 모델이 문자열 "null"을 흘리는 등 불안정해서,
# 미포함을 None으로 읽는 쪽이 안전하다(호출부가 .get()으로 받는다).
_SUPERVISOR_TOOL = {
    "type": "function",
    "function": {
        "name": "assess_situation",
        "description": "사용자 발화에서 상황의 각 축을 독립적으로 판별한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "recognized": {
                    "type": "boolean",
                    "description": "이미 법적으로 전세사기 피해자로 인정받은 상태라고 밝혔는지",
                },
                "risk_signals": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(RISK_SIGNALS)},
                    "description": "발화에서 확인되는 위험신호 (없으면 빈 배열)",
                },
                "topic": {"type": "string", "enum": list(GENERAL_TOPIC_LABELS), "description": "일반 시나리오 13개 항목"},
                "special_case": {"type": "string", "enum": list(SPECIAL_CASE_CATEGORIES), "description": "특수상황 4종"},
                "reason": {"type": "string", "description": "판단 근거 한 줄"},
            },
            "required": ["recognized", "risk_signals"],
        },
    },
}


_CONFIRMATION_TOOL = {
    "type": "function",
    "function": {
        "name": "confirm",
        "description": "확인 질문에 대한 사용자 응답을 yes/no/unclear로 판별한다.",
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {"type": "string", "enum": ["yes", "no", "unclear"]},
                "reason": {"type": "string", "description": "판단 근거 한 줄"},
            },
            "required": ["answer"],
        },
    },
}


def _read_prompt(prompt_name: str) -> str:
    return (_PROMPTS_DIR / f"{prompt_name}.md").read_text(encoding="utf-8")


def _render_prompt(prompt_name: str, **kwargs) -> str:
    context_lines = "\n".join(f"{key}: {value}" for key, value in kwargs.items())
    return f"{_read_prompt(prompt_name)}\n\n---\n\n{context_lines}"


# 답변 성격별 프롬프트. 모든 경로가 한 장을 공유하던 때는 "판단 결과가 없으면 …", "근거가 없으면 …"
# 같은 조건이 프롬프트 안에 쌓여, 모델이 자기 경로에 해당하지 않는 지시까지 읽어야 했다.
# 이제 각 경로는 자기 지시만 받는다. 인용·형식 규칙은 경로별로 복제하면 드리프트가 나므로
# response_common에 한 번만 두고 앞에 붙인다.
RESPONSE_ANSWER_KINDS = ("judgment", "scenario", "special_case", "recognized_general", "open_qa")


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


async def _call_tool(prompt_name: str, tool: dict, model: str = MODEL, **kwargs) -> dict:
    """_call_structured와 달리 응답을 텍스트로 받아 JSON 파싱하지 않고, OpenAI tool
    calling으로 스키마(enum)를 강제해 모델이 정의된 카테고리 밖의 값을 반환할 수
    없게 한다. 스트리밍 대상이 아니라 stream=False로 호출한다."""
    prompt = _render_prompt(prompt_name, **kwargs)
    tool_name = tool["function"]["name"]
    for attempt in range(MAX_RETRIES):
        try:
            response = await _client.chat.completions.create(
                model=model,
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


async def call_victim_check(user_input: str, existing_slots: dict, pending_question: str | None = None) -> dict:
    return await _call_structured(
        "victim_check",
        user_input=user_input,
        existing_slots=existing_slots,
        pending_question=pending_question or "(없음 — 사용자가 먼저 상황을 서술한 턴)",
    )


async def call_supervisor(user_input: str) -> dict:
    """상황의 축별 판별 결과를 dict로 반환한다(SituationState 필드에 대응).
    topic/special_case는 해당 없으면 키 자체가 빠져 온다 — 호출부가 .get()으로 읽는다."""
    return await _call_tool("supervisor", _SUPERVISOR_TOOL, user_input=user_input)


async def call_query_expansion(user_input: str) -> str:
    """발화를 법령·판례 벡터검색용 질의로 바꿔 한 줄로 반환한다(검색 전용).

    구어와 법조문의 어휘 간극 때문에 발화를 그대로 임베딩하면 정답 조문이 한참 뒤로 밀린다 —
    실측: "이사를 먼저 나가도 보증금 돌려받을 권리가 유지되나요"에서 임차권등기명령(주택임대차
    보호법 제3조의3)이 법령원문 932건 중 29위(쿼터는 top2만 가져간다). 확장하면 1위가 된다.

    싼 모델을 쓰지 않는다. gpt-4o-mini는 "무관한 발화는 그대로 두라"는 지시를 어기고 "김치찌개
    끓이는 법"을 "김치찌개 조리법에 대한 질문입니다"로 다듬어, 거리가 임계값(0.65) 아래인
    0.614로 내려가 무관 질문에 법령이 걸렸다(실측). '근거 없음'으로 빠져야 할 자리에서 답변이
    생성되는 안전성 회귀라 확장은 본 모델로 한다.
    """
    raw = await _call_llm(_render_prompt("query_expansion", user_input=user_input))
    return _strip_code_fence(raw).strip()


async def call_confirmation(question: str, user_input: str) -> dict:
    return await _call_tool(
        "confirmation",
        _CONFIRMATION_TOOL,
        model=CONFIRMATION_MODEL,
        question=question,
        user_input=user_input,
    )


async def generate_response(context: str, answer_kind: str) -> AsyncGenerator[str, None]:
    """최종 응답(해설→상황적용) 진짜 토큰 스트리밍 — 다른 call_*와 달리 전체를 모아
    JSON 파싱하지 않고 그대로 흘려보낸다. 스트림 시작 후 실패하면 이미 클라이언트로
    청크가 나간 상태라 재시도하지 않고 그대로 전파한다.

    answer_kind는 호출 노드가 자기 경로를 알려주는 값이다(RESPONSE_ANSWER_KINDS).
    같은 두 단계를 쓰더라도 판정 유무·상황 정보 유무가 달라 지시가 갈린다.
    """
    if answer_kind not in RESPONSE_ANSWER_KINDS:
        raise ValueError(f"알 수 없는 answer_kind: {answer_kind!r}")
    prompt = (
        f"{_read_prompt('response_common')}\n\n{_read_prompt(f'response_{answer_kind}')}"
        f"\n\n---\n\ncontext: {context}"
    )
    stream = await _client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )
    async for event in stream:
        content = event.choices[0].delta.content
        if content:
            yield content
