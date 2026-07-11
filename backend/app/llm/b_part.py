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
DEFAULT_MODEL = os.getenv("B_PART_LLM_MODEL", "gpt-4o-mini")


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
- 어려운 법률 용어는 중학생도 이해할 수 있게 풀어 씁니다.
- 보증금 반환, 임차권등기명령, 대항력 등 계약 종료 이후 이슈는 핵심 답변이 아니라 주의사항 수준으로만 언급합니다.

반드시 아래 형식을 사용하세요.

① 결론
② 쉬운 설명
③ 법적 근거
④ 관련 판례
⑤ 추천 행동
⑥ 주의사항
⑦ 추가 확인 질문
""".strip()


def format_retrieved_documents(retrieved_documents: list[dict[str, Any]]) -> str:
    """GPT 프롬프트에 넣기 좋게 검색 결과를 짧게 정리합니다."""
    if not retrieved_documents:
        return "검색된 법령/판례가 없습니다."

    blocks: list[str] = []
    for index, document in enumerate(retrieved_documents, start=1):
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

[부족하거나 추가 확인할 정보]
{missing_text}

[검색된 법령/판례/해설]
{format_retrieved_documents(retrieved_documents)}

[작성 지시]
- 사용자의 질문에 먼저 답하고, 필요한 경우 추가 확인 질문을 마지막에 붙이세요.
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
    )

    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": SYSTEM_PROMPT},
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
