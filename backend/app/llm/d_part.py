"""
D파트 프롬프트 조립 + GPT-4o 호출.
d파트 담당자만 이 파일을 수정합니다.
프롬프트 내용/조립 방식은 graph/parts/d_part/prompts/*.md 를 참고합니다.

app/llm/base.py::call_llm_stream_raw는 아직 미구현 스텁이라 이 파일에서 자체 OpenAI
클라이언트로 직접 호출한다.

⚠️ 예전 주석은 이를 두고 "base.py를 쓰는 다른 파트 컨벤션과는 다른 방식"이라고 적었는데
사실이 아니다(2026-07-19 전수 확인) — base.py를 쓰는 파트는 하나도 없고, A파트는
responses.parse, B파트는 responses.create, C파트는 LangChain ChatOpenAI로 각자 다르다.
즉 팀 컨벤션이라 부를 것이 없다. 그래서 프레임워크를 맞추는 마이그레이션(ChatOpenAI 전환)은
근거가 없다고 보고 하지 않는다.

OpenAI Responses API 전환은 A·B와 API 표면이 정렬된다는 실익이 있으나 보류했다 —
generate_response가 레포에서 유일한 진짜 토큰 스트리밍 경로라 SSE 이벤트 형태까지 재검증해야
하고, 골든셋으로 확보한 지표(라우팅 78건·판정 8시나리오)를 걸 만한 이득이 아니다.
나중에 A·B와 정렬할 일이 생기면 다시 꺼낼 것.

구조화된 값을 받는 경로는 둘이다. 슬롯 추출처럼 형태가 정해진 값은 strict json_schema를 쓰는
_call_parsed로, 카테고리 분류는 tool calling을 쓰는 _call_tool로 받는다. 둘 다 응답을 텍스트로
파싱하지 않는다. 다만 strict 적용 범위는 도구마다 다르다 — 확인 게이트는 strict를 켰지만
supervisor는 실측 결과 켜지 않았다(_SUPERVISOR_TOOL 주석 참고).

_call_llm은 스트리밍으로 받아 전체 텍스트로 모아 반환한다 — 이제 형태가 없는 산문을 받는
call_query_expansion 전용이다. 실제 enum/pydantic 모델로의 변환은 호출하는 노드 쪽 책임이다.
"""
import asyncio
import json
from pathlib import Path
from typing import AsyncGenerator

from langsmith.wrappers import wrap_openai
from openai import APIError, APIStatusError, AsyncOpenAI, LengthFinishReasonError, RateLimitError
from pydantic import BaseModel

from app.core.config import settings
from app.graph.parts.d_part.schemas import (
    GENERAL_TOPIC_LABELS,
    RISK_SIGNALS,
    SPECIAL_CASE_CATEGORIES,
    VictimSlotExtraction,
)

MODEL = "gpt-4o"
# 확인 응답 판별은 예/아니오/불명확 3-way 분류라 법률지식이 필요 없고 매 턴 호출되므로
# 더 싼 모델을 쓴다. 단위 21′에서 로컬모델(EXAONE)로 스왑 검토 예정.
CONFIRMATION_MODEL = "gpt-4o-mini"
MAX_RETRIES = 3
# 분류·구조화 추출 경로의 샘플링 온도. 지정하지 않으면 OpenAI 기본값 1.0이 걸려 같은 발화가
# 실행마다 다른 축으로 분류된다 — 라우팅 골든셋 42건을 같은 코드로 4회 돌렸을 때 경로 정확도가
# 92.9~97.6%로 흔들렸고(2026-07-19 실측), 이 산포가 개선 1건의 효과(2.4%p)와 같은 크기라
# 무엇을 고쳐도 효과를 노이즈와 구분할 수 없었다. enum으로 제약된 분류에 샘플링을 걸 이유가
# 없으므로 0으로 고정한다. 답변 산문 생성(generate_response)에는 적용하지 않는다.
STRUCTURED_TEMPERATURE = 0.0

# LangGraph 노드 span은 LANGSMITH_TRACING=true만으로 자동 캡처되지만, d파트는 LangChain
# 래퍼가 아니라 raw SDK를 쓰므로 그 노드 '안'의 LLM 호출(프롬프트·토큰·모델·지연)은 안 잡힌다.
# 클라이언트가 이 한 곳뿐이라 여기서 감싸면 9개 호출 지점이 전부 커버된다.
# LANGSMITH_TRACING이 꺼져 있으면 wrap_openai는 순수 패스스루라 키 없는 팀원 환경엔 영향이 없다.
_client = wrap_openai(AsyncOpenAI(api_key=settings.openai_api_key))


class ToolCallMissing(RuntimeError):
    """tool_choice로 강제했는데도 모델이 tool call을 내지 않았다.

    finish_reason이 length(토큰 소진)이거나 거절(refusal)이면 실제로 일어난다. 예전엔
    tool_calls[0]을 곧바로 인덱싱해 TypeError/IndexError가 났는데, 그건 아래 재시도 루프가
    잡는 예외가 아니라서 재시도 없이 노드까지 그대로 올라갔다(2026-07-19).

    strict schema를 켜도 이 문제는 남는다 — strict는 tool call이 '나왔을 때' 인자가 스키마를
    지키는지만 보장하지, tool call이 나오는지는 보장하지 않는다.
    """


def _is_retryable(exc: Exception) -> bool:
    """재시도가 의미 있는 실패인지. 4xx는 같은 요청을 다시 보내도 같은 답이 온다.

    특히 400(BadRequestError)은 스키마가 잘못됐다는 뜻인데 APIError 하위라, 걸러내지 않으면
    2s→4s 백오프로 3번 재시도한 뒤에야 터진다. 골든셋 78건을 돌리면 스키마 실수 하나가
    '느린 실패'로 위장돼 평가를 몇 분간 조용히 갈아먹는다. 429(RateLimit)만 예외로 재시도한다.
    """
    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code >= 500
    return True  # 연결/타임아웃 등 전송 계층 실패와 ToolCallMissing은 재시도 대상


_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "graph" / "parts" / "d_part" / "prompts"

# supervisor는 카테고리 하나가 아니라 상황의 축을 각각 판별한다(SituationState). 예전엔 축들이
# 카테고리 enum 하나로 압축돼 있어 인지여부가 topic에 가려지는 등 축끼리 서로를 덮어썼다.
# enum 값은 schemas.py의 상수와 그대로 맞물려야 general_scenario.py/special_cases.py의 실행부가
# 같은 키로 조회할 수 있다.
#
# topic/special_case는 "해당 없음"이 정상값이라 required에 넣지 않는다 — JSON Schema의
# null 유니온은 비-strict tool calling에서 모델이 문자열 "null"을 흘리는 등 불안정해서,
# 미포함을 None으로 읽는 쪽이 안전하다(호출부가 .get()으로 받는다).
#
# ⚠️ 이 도구에 strict를 켜지 마라. 실험했고 되돌렸다(2026-07-19).
# strict는 모든 property를 required로 요구하므로 topic/special_case를 anyOf[enum, null]로 바꾸고
# 프롬프트의 "인자를 넘기지 마세요"를 "null을 넘기세요"로 함께 고쳐야 한다. 그렇게 했더니
# 라우팅 골든셋 78건이 100% → 96.2%로 떨어졌다(2회 실행 동일, 실패 케이스도 같아 노이즈가 아님).
# 예상은 topic 과탐이었는데 실제로 무너진 건 risk_signals 재현율이었다 —
# micro-F1 0.960(TP12 FP0 FN1) → 0.783(TP9 FP1 FN4). 모든 축을 강제로 채우게 하면 모델이
# 위험신호 검출에 쓰던 주의를 다른 축 결정에 나눠 쓰는 것으로 보인다.
#
# 얻는 것과 비교하면 남는 장사가 아니다. strict가 막아주는 건 어휘 이탈인데, 그건 SituationState의
# validator가 이미 잡고 있고(그 방어는 JSONB에서 복원되는 옛 세션 때문에 어차피 남겨야 한다)
# 실제로 문제를 일으킨 적도 없다. 3.8%p를 주고 살 가치가 없다.
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


# strict를 켜면 enum 밖의 값이 API 디코더 레벨에서 막힌다. 이 경로는 gpt-4o-mini가 돌리는데,
# 작은 모델일수록 enum을 벗어날 확률이 높고 answer가 세 값 밖으로 나가면 parse_confirmation이
# None(=재질문)으로 떨어뜨린다 — 구제수단 게이트에서 그건 부당 제외로 이어질 수 있는 방향이다.
# strict는 모든 property를 required로 요구하므로 reason도 필수가 되는데, reason은 아무도 읽지 않아
# 영향이 없다.
_CONFIRMATION_TOOL = {
    "type": "function",
    "function": {
        "name": "confirm",
        "description": "확인 질문에 대한 사용자 응답을 yes/no/unclear로 판별한다.",
        "strict": True,
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "answer": {"type": "string", "enum": ["yes", "no", "unclear"]},
                "reason": {"type": "string", "description": "판단 근거 한 줄"},
            },
            "required": ["answer", "reason"],
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
                temperature=STRUCTURED_TEMPERATURE,
                stream=True,
            )
            return "".join([event.choices[0].delta.content or "" async for event in stream])
        except APIError as exc:
            if attempt == MAX_RETRIES - 1 or not _is_retryable(exc):
                raise
            await asyncio.sleep(2**attempt)
    # MAX_RETRIES=0이면 루프가 한 번도 안 돌아 암묵적으로 None이 반환된다. 그러면 호출부가
    # 한참 떨어진 곳에서 터지므로(옛 _call_structured는 json.loads(None)) 여기서 끊는다.
    raise RuntimeError(f"unreachable: MAX_RETRIES={MAX_RETRIES}로는 호출이 한 번도 실행되지 않는다")


def _strip_code_fence(text: str) -> str:
    """모델이 응답을 ```...``` 코드펜스로 감싸서 반환하는 경우가 있어 벗겨낸다
    (실제 라이브 호출에서 확인된 동작 — monkeypatch 테스트는 순수 문자열만 흉내내
    이 문제를 못 잡았음, 2026-07-11).

    이제 call_query_expansion 전용이다. 구조화 추출(call_victim_check)은 strict json_schema로
    옮겨가 형태를 API가 보장하므로 이 방어가 필요 없어졌다. 확장 질의는 한 줄 산문이라
    스키마를 씌울 이유가 없어 여기 남는다.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text.removeprefix("```")
        text = text.removesuffix("```").strip()
    return text


async def _call_parsed(prompt_name: str, schema: type[BaseModel], **kwargs) -> dict:
    """스키마가 곧 계약인 구조화 추출.

    예전 _call_structured는 산문 JSON을 받아 코드펜스를 벗기고 json.loads로 파싱했다.
    모델이 형식을 어기면 그대로 터졌고, 키를 빼먹으면 호출부가 KeyError를 냈다. strict
    json_schema로 옮기면 그 분기 자체가 사라진다 — 형태를 API가 보장한다.

    스트리밍을 쓰지 않는다. 이 경로는 어차피 전체를 모아 파싱했고(_call_llm이 join),
    사용자에게 첫 토큰이 노출되지 않는 내부 호출이라 스트리밍이 아무 값도 주지 않았다.
    진짜 토큰 스트리밍이 필요한 건 generate_response 하나뿐이다.

    반환을 모델이 아니라 dict로 두는 건 호출부 계약을 유지하기 위해서다 — 노드와 테스트가
    call_victim_check의 dict 반환에 맞춰져 있다.

    ⚠️ 이 경로를 타면 "PydanticSerializationUnexpectedValue ... field_name='parsed'" 경고가
    한 줄 뜬다. 우리 코드가 아니라 wrap_openai가 ParsedChatCompletion을 직렬화하면서 내는
    것이고(순수 AsyncOpenAI로는 0건, 래핑하면 1건 — 2026-07-19 격리 확인),
    LANGSMITH_TRACING과 무관하게 뜬다. 파싱된 값 자체는 정상이라 동작에 영향이 없다.
    """
    prompt = _render_prompt(prompt_name, **kwargs)
    for attempt in range(MAX_RETRIES):
        try:
            response = await _client.chat.completions.parse(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=STRUCTURED_TEMPERATURE,
                response_format=schema,
            )
            choice = response.choices[0]
            if choice.message.parsed is None:
                raise ToolCallMissing(
                    f"{schema.__name__}: finish_reason={choice.finish_reason}, "
                    f"refusal={choice.message.refusal!r}"
                )
            return choice.message.parsed.model_dump(mode="json")
        except (ToolCallMissing, APIError, LengthFinishReasonError) as exc:
            if attempt == MAX_RETRIES - 1 or not _is_retryable(exc):
                raise
            await asyncio.sleep(2**attempt)
    raise RuntimeError(f"unreachable: MAX_RETRIES={MAX_RETRIES}로는 호출이 한 번도 실행되지 않는다")


async def _call_tool(prompt_name: str, tool: dict, model: str = MODEL, **kwargs) -> dict:
    """응답을 텍스트로 파싱하지 않고 OpenAI tool calling으로 스키마(enum)를 강제해, 모델이
    정의된 카테고리 밖의 값을 반환할 수 없게 한다. 스트리밍 대상이 아니라 stream=False로 호출한다.

    ⚠️ `parallel_tool_calls=False`를 넣지 말 것. strict function calling 문서가 이를 요구한다고
    되어 있어 넣어봤는데, 넣지 않아도 strict가 정상 동작하고(400 없음) 넣으면 supervisor 분류가
    흔들렸다 — 라우팅 골든셋 78건이 100%×2에서 97.4~98.7%로 떨어졌고 hrd-003("이미 보증보험으로
    돌려받았는데 처벌할 수 있나요")이 3/3 실패했다. 빼면 100%×2로 돌아온다(2026-07-19, 5회 실측).
    tool_choice로 이미 단일 함수를 강제하므로 병렬 호출이 애초에 불가능해 넣을 이유도 없다.
    """
    prompt = _render_prompt(prompt_name, **kwargs)
    tool_name = tool["function"]["name"]
    for attempt in range(MAX_RETRIES):
        try:
            response = await _client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=STRUCTURED_TEMPERATURE,
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": tool_name}},
            )
            choice = response.choices[0]
            calls = choice.message.tool_calls
            if not calls:
                # tool_choice로 강제했어도 length 소진·거절이면 tool call 없이 돌아온다.
                # 재시도 대상에 넣는 건 length가 재호출로 회복될 수 있어서다 — refusal은
                # 재시도해도 안 되지만 3회 낭비가 라우팅을 통째로 죽이는 것보다 싸다.
                raise ToolCallMissing(
                    f"{tool_name}: finish_reason={choice.finish_reason}, refusal={choice.message.refusal!r}"
                )
            return json.loads(calls[0].function.arguments)
        except (ToolCallMissing, APIError, LengthFinishReasonError) as exc:
            if attempt == MAX_RETRIES - 1 or not _is_retryable(exc):
                raise
            await asyncio.sleep(2**attempt)
    raise RuntimeError(f"unreachable: MAX_RETRIES={MAX_RETRIES}로는 호출이 한 번도 실행되지 않는다")


async def call_victim_check(user_input: str, existing_slots: dict, pending_question: str | None = None) -> dict:
    return await _call_parsed(
        "victim_check",
        VictimSlotExtraction,
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
