"""
B파트 계약 중 분쟁 답변 생성기.

Retriever가 찾은 법령/판례 청크와 사용자 질문을 GPT에 전달해
결론, 쉬운 설명, 법적 근거, 추천 행동, 주의사항, 추가 확인 질문 형식의 답변을 만듭니다.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, AsyncGenerator


BACKEND_DIR = Path(__file__).resolve().parents[2]


def load_local_env() -> None:
    """python-dotenv 의존성 없이 backend/.env 값을 환경변수로 읽습니다."""
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DEFAULT_MODEL = os.getenv("B_PART_LLM_MODEL", "gpt-4o")


SYSTEM_PROMPT = """
당신은 한국 주택임대차 계약 중 분쟁을 쉬운 말로 설명하는 법률 정보 안내 챗봇입니다.

담당 범위:
- 계약갱신, 계약갱신요구권, 묵시적갱신
- 차임증감, 전월세전환
- 임대인의무, 수선의무
- 계약해지, 계약 중 손해배상

응답 원칙:
- 법률 상담이 아니라 정보 제공이라는 점을 밝혀야 합니다.
- 단정 대신 "가능성이 있습니다", "추가 확인이 필요합니다", "가능성은 낮아 보입니다"처럼 표현합니다.
- 날짜 계산, 금액 계산, 5% 초과 여부 같은 계산은 직접 확정하지 말고 Rule Engine 확인 대상으로 안내합니다.
- 검색된 법령/판례 근거에 없는 내용은 과장하지 않습니다.
- 법적 근거를 설명할 때는 검색된 문서 중 source_type이 law인 법령 문서를 우선 사용합니다.
- 판례는 질문과 직접 관련성이 높은 경우에만 언급합니다.
- 검색 결과에 직접 관련 판례가 없거나 관련성이 낮으면 "현재 검색 결과만으로는 직접 맞는 판례를 특정하기 어렵습니다"라고 말합니다.
- 검색 결과에 없는 조문명이나 판례를 새로 만들어내지 않습니다.
- 법령 문서와 판례 문서가 충돌하거나 판례 관련성이 낮아 보이면 법령 문서를 기준으로 설명합니다.
- 어려운 법률 용어는 중학생도 이해할 수 있게 풀어 씁니다.
- 보증금 반환, 임차권등기명령, 대항력 등 계약 종료 이후 이슈는 핵심 답변이 아니라 주의사항 수준으로만 언급합니다.
- 최종 답변이 가능한 상황에서는 추가 확인 질문을 0~1개만 작성합니다.
- 사용자가 이미 제공한 날짜, 금액, 기간, 하자 내용은 다시 묻지 않습니다.
- 선택 정보가 부족하다는 이유만으로 답변을 흐리지 말고, 필요한 경우 가장 중요한 확인 질문 1개만 남깁니다.

반드시 아래 형식을 사용하세요.

① 결론
② 쉬운 설명
③ 법적 근거
④ 관련 판례
⑤ 추천 행동
⑥ 주의사항
⑦ 추가 확인 질문
""".strip()


ANSWER_STYLE_GUIDE = """
[최종 답변 디자인 규칙]
답변은 사용자가 빠르게 훑어볼 수 있도록 아래 형식을 반드시 지키세요.
마크다운 표는 사용하지 말고, 줄바꿈과 짧은 목록을 사용하세요.
각 섹션 사이에는 빈 줄을 하나 넣으세요.

① 결론
- 첫 문장은 사용자의 질문에 대한 직접 답변으로 시작하세요.
- 날짜나 금액 계산 결과가 있으면 결론에 가장 먼저 적으세요.
- 단정이 어려우면 "가능성이 있습니다", "추가 확인이 필요합니다"처럼 표현하세요.

② 쉬운 설명
쉽게 말하면, ...
- 법률 용어를 풀어서 2~4문장으로 설명하세요.
- 사용자가 이미 제공한 날짜, 금액, 기간은 다시 묻지 말고 설명에 반영하세요.

③ 법적 근거
- 법령명과 조문명을 먼저 쓰고, 그 조문이 이 상황에 왜 중요한지 한 문장으로 설명하세요.
- 검색된 법령 근거가 있으면 판례보다 법령을 우선하세요.

④ 관련 판례
- 직접 관련성이 높은 판례가 있을 때만 간단히 요지를 쓰세요.
- 직접 관련성이 낮으면 "현재 검색 결과만으로는 직접 맞는 판례를 특정하기 어렵습니다."라고 한 문장만 쓰세요.

⑤ 추천 행동
1. 가장 먼저 할 일
2. 증거로 남길 일
3. 필요하면 다음 절차
- 사용자가 바로 따라 할 수 있는 순서로 2~4개만 작성하세요.

⑥ 주의사항
- 과장하지 말고, 사용자가 놓치기 쉬운 위험만 1~3개 적으세요.
- B파트 범위 밖인 보증금 반환, 임차권등기명령, 대항력은 필요할 때만 짧게 언급하세요.

⑦ 추가 확인 질문
- 추가 정보가 꼭 필요하면 질문 1개만 작성하세요.
- 더 물을 것이 없으면 "현재 추가 확인 질문은 없습니다."라고 쓰세요.
- 사용자가 이미 말한 날짜, 금액, 기간, 증거 여부를 다시 묻지 마세요.

⑧ 캘린더 등록 가능 일정
Calendar Event Candidates가 있을 때만 이 섹션을 작성하세요.
아래 일정은 캘린더에 등록할 수 있습니다. 실제 등록 전에는 사용자 확인이 필요합니다.

1. 일정 제목
   날짜: YYYY-MM-DD
   설명: 한 문장 설명

2. 일정 제목
   날짜: YYYY-MM-DD
   설명: 한 문장 설명

[문체]
- 문장은 짧고 또렷하게 작성하세요.
- "따라서", "다만", "쉽게 말하면"처럼 연결어를 사용해 흐름을 자연스럽게 만드세요.
- 같은 내용을 반복하지 마세요.
""".strip()


def format_rule_results(rule_results: list[dict[str, Any]] | None) -> str:
    """
    Rule Engine 계산 결과를 GPT 프롬프트에 넣기 좋은 문자열로 변환합니다.
    """
    if not rule_results:
        return "Rule Engine 계산 결과가 없습니다."

    blocks: list[str] = []

    for index, result in enumerate(rule_results, start=1):
        rule_name = result.get("rule_name", "규칙 계산")
        rule_type = result.get("rule_type", "unknown")

        lines = [
            f"[계산 결과 {index}]",
            f"- 규칙명: {rule_name}",
            f"- 규칙 유형: {rule_type}",
        ]

        for key, value in result.items():
            if key in {"rule_name", "rule_type"}:
                continue
            lines.append(f"- {key}: {value}")

        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def format_calendar_events(calendar_events: list[dict[str, Any]] | None) -> str:
    """
    캘린더 등록 후보 일정을 GPT 프롬프트에 넣기 좋은 문자열로 변환합니다.
    """
    if not calendar_events:
        return "캘린더 등록 후보 일정이 없습니다."

    blocks: list[str] = []

    for index, event in enumerate(calendar_events, start=1):
        lines = [
            f"[일정 후보 {index}]",
            f"- 제목: {event.get('title', '일정')}",
            f"- 날짜: {event.get('date', '')}",
            f"- 설명: {event.get('description', '')}",
            f"- 일정 유형: {event.get('event_type', '')}",
        ]
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def format_retrieved_documents(
    retrieved_documents: list[dict[str, Any]],
    categories: list[str] | None = None,
) -> str:
    """GPT 프롬프트에 넣기 좋게 검색 결과를 짧게 정리합니다."""
    if not retrieved_documents:
        return "검색된 법령/판례가 없습니다."

    category_set = set(categories or [])
    law_documents = [
        document
        for document in retrieved_documents
        if (document.get("source_type") or (document.get("metadata") or {}).get("document_type")) == "law"
    ]
    precedent_documents = []
    for document in retrieved_documents:
        metadata = document.get("metadata") or {}
        source_type = document.get("source_type") or metadata.get("document_type")
        if source_type != "precedent":
            continue

        similarity = float(document.get("similarity") or 0)
        category = document.get("category") or metadata.get("category")
        if similarity >= 0.34 and (not category_set or category in category_set):
            precedent_documents.append(document)

    display_documents = law_documents + precedent_documents
    if not display_documents:
        display_documents = law_documents or retrieved_documents[:3]

    blocks: list[str] = []
    for index, document in enumerate(display_documents, start=1):
        metadata = document.get("metadata") or {}
        title = document.get("title") or metadata.get("title") or "제목 없음"
        category = document.get("category") or metadata.get("category") or "카테고리 없음"
        source_type = document.get("source_type") or metadata.get("document_type") or "출처 없음"
        chunk_type = document.get("chunk_type") or metadata.get("chunk_type") or "청크 유형 없음"
        similarity = document.get("similarity")
        content = str(document.get("content", "")).strip()

        if len(content) > 1200:
            content = f"{content[:1200]}..."

        similarity_text = f"{similarity:.4f}" if isinstance(similarity, float) else "N/A"
        blocks.append(
            "\n".join(
                [
                    f"[문서 {index}]",
                    f"- 제목: {title}",
                    f"- 카테고리: {category}",
                    f"- 출처 유형: {source_type}",
                    f"- 청크 유형: {chunk_type}",
                    f"- 유사도: {similarity_text}",
                    f"- 내용: {content}",
                ]
            )
        )

    return "\n\n".join(blocks)


def build_b_part_answer_prompt(
    user_question: str,
    retrieved_documents: list[dict[str, Any]],
    categories: list[str] | None = None,
    missing_questions: list[str] | None = None,
    rule_results: list[dict[str, Any]] | None = None,
    calendar_events: list[dict[str, Any]] | None = None,
) -> str:
    """사용자 질문, 의도, 검색 결과를 하나의 프롬프트로 조립합니다."""
    category_text = ", ".join(categories or []) if categories else "분류 전"
    missing_text = "\n".join(f"- {question}" for question in (missing_questions or []))
    if not missing_text:
        missing_text = "- 현재 단계에서 바로 확인된 필수 추가 질문은 없습니다."

    return f"""
[사용자 질문]
{user_question}

[예상 분쟁 카테고리]
{category_text}

[Rule Engine 계산 결과]
{format_rule_results(rule_results)}

[Calendar Event Candidates]
{format_calendar_events(calendar_events)}

Calendar Event Candidates가 있으면 답변 마지막에 "캘린더 등록 가능 일정" 섹션을 추가하고, 실제 등록 전 사용자 확인이 필요하다고 안내하세요.

[부족하거나 추가 확인할 정보]
{missing_text}

[검색된 법령/판례/해설]
{format_retrieved_documents(retrieved_documents, categories=categories)}

[작성 지시]
- 사용자의 질문에 먼저 답하고, 필요한 경우 추가 확인 질문을 마지막에 붙이세요.
- [부족하거나 추가 확인할 정보]는 후보 목록입니다. 최종 답변이 가능한 경우 전부 쓰지 말고 가장 중요한 질문 0~1개만 쓰세요.
- ⑦ 추가 확인 질문에는 최대 1개의 질문만 작성하세요. 더 물을 것이 없으면 "현재 추가 확인 질문은 없습니다."라고 쓰세요.
- 같은 의미의 질문을 반복하지 마세요.
- 날짜, 금액, 인상률, 5% 초과 여부는 Rule Engine 계산 결과가 있으면 그 값을 우선 사용하세요.
- Rule Engine 계산 결과가 없는 날짜/금액 판단은 직접 확정하지 말고 추가 확인이 필요하다고 말하세요.
- 차임증감 질문에서 Rule Engine 계산 결과가 없으면 현재 월세와 요구 월세가 필요하다고 반드시 안내하세요.
- 검색 결과의 제목이나 조문명을 법적 근거에 포함하세요.
- 관련 판례가 검색 결과에 없거나 관련성이 낮으면 "현재 검색 결과만으로는 직접 맞는 판례를 특정하기 어렵습니다"라고 말하세요.
- 추천 행동은 사용자가 바로 할 수 있는 순서로 작성하세요.
""".strip()


def _extract_response_text(response: Any) -> str:
    """OpenAI Responses API 결과에서 텍스트를 꺼냅니다."""
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text).strip()

    texts: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                texts.append(str(text))
    return "\n".join(texts).strip()


def generate_b_part_answer(
    user_question: str,
    retrieved_documents: list[dict[str, Any]],
    categories: list[str] | None = None,
    missing_questions: list[str] | None = None,
    rule_results: list[dict[str, Any]] | None = None,
    calendar_events: list[dict[str, Any]] | None = None,
    model: str = DEFAULT_MODEL,
) -> str:
    """Responses API로 B파트 최종 답변을 생성합니다."""
    if not OPENAI_API_KEY:
        raise ValueError("B파트 답변 생성을 위해 OPENAI_API_KEY가 필요합니다.")

    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt = build_b_part_answer_prompt(
        user_question=user_question,
        retrieved_documents=retrieved_documents,
        categories=categories,
        missing_questions=missing_questions,
        rule_results=rule_results,
        calendar_events=calendar_events,
    )

    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{ANSWER_STYLE_GUIDE}"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    answer = _extract_response_text(response)
    if not answer:
        raise RuntimeError("OpenAI 응답에서 답변 텍스트를 찾지 못했습니다.")
    return answer


async def stream_text(text: str) -> AsyncGenerator[str, None]:
    """FastAPI StreamingResponse에서 사용할 수 있도록 문단 단위로 흘려보냅니다."""
    paragraphs = text.split("\n")
    for paragraph in paragraphs:
        yield paragraph + "\n"
