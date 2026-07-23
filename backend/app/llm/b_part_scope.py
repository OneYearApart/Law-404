"""
B파트 LLM Scope Analyzer.

이 모듈은 법률 답변을 생성하지 않고, 사용자 질문이 B파트 담당 범위인지
먼저 판단합니다. 키워드 기반 제외 규칙으로 잡히지 않는 애매한 질문을
RAG/GPT 답변 생성 전에 걸러내기 위한 보조 장치입니다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = os.getenv("B_PART_SCOPE_MODEL", os.getenv("B_PART_LLM_MODEL", "gpt-4o"))

B_PART_CATEGORIES = {
    "계약갱신",
    "계약갱신요구권",
    "묵시적갱신",
    "차임증감",
    "전월세전환",
    "임대인의무",
    "수선의무",
    "계약해지",
    "손해배상",
}

VALID_SCOPES = {"in_scope", "out_of_scope", "ambiguous"}


def load_local_env() -> None:
    """backend/.env 값을 환경변수로 읽습니다."""
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


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


def _extract_json_object(text: str) -> dict[str, Any]:
    """LLM 응답에서 JSON 객체만 추출합니다."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or start > end:
        return {}

    try:
        value = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return {}

    return value if isinstance(value, dict) else {}


def _normalize_scope(scope: Any) -> str:
    if isinstance(scope, str) and scope in VALID_SCOPES:
        return scope
    return "ambiguous"


def _normalize_categories(categories: Any) -> list[str]:
    if not isinstance(categories, list):
        return []

    normalized: list[str] = []
    for category in categories:
        if not isinstance(category, str):
            continue
        if category in B_PART_CATEGORIES and category not in normalized:
            normalized.append(category)
    return normalized


def analyze_b_part_scope(question: str, model: str = DEFAULT_MODEL) -> dict[str, Any]:
    """
    질문이 B파트 범위인지 판단합니다.

    반환값은 항상 dict이며, OpenAI 호출/파싱 실패 시 ambiguous로 처리합니다.
    """
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return {
            "source": "llm_skipped",
            "scope": "ambiguous",
            "reason": "OPENAI_API_KEY가 없어 범위 판단을 보류했습니다.",
            "suggested_categories": [],
            "clarification_question": "주택임대차 계약 중 어떤 문제인지 조금 더 구체적으로 알려주세요.",
        }

    from openai import OpenAI

    system_prompt = """
당신은 한국 주택임대차 서비스의 B파트 Scope Analyzer입니다.
법률 답변을 생성하지 말고, 반드시 JSON 객체 하나만 반환하세요.

B파트 범위:
- 주택임대차 계약을 이미 체결했고 실제 거주 중인 상태의 분쟁
- 계약갱신
- 계약갱신요구권
- 묵시적갱신
- 차임증감
- 전월세전환
- 임대인의무
- 수선의무
- 계약 중도해지
- 계약 중 손해배상

B파트 범위 밖:
- 계약 전 위험 분석
- 전세사기
- 등기부등본 분석
- 보증금 반환
- 임차권등기명령
- 대항력/우선변제권/최우선변제권
- 경매/배당
- 명도
- 원상회복
- 상가/점포/사무실/공장/토지 임대차
- 주택임대차와 무관한 일반 다툼

판단 규칙:
- B파트 범위가 명확하면 scope를 in_scope로 설정하세요.
- B파트 범위 밖이 명확하면 scope를 out_of_scope로 설정하세요.
- 질문이 너무 짧거나 맥락이 부족해 판단이 어렵다면 scope를 ambiguous로 설정하세요.
- ambiguous인 경우에는 법률 답변 대신 확인 질문을 clarification_question에 작성하세요.
- suggested_categories에는 B파트 범위일 가능성이 있을 때만 허용 카테고리 중에서 넣으세요.

반환 형식:
{
  "scope": "ambiguous",
  "reason": "질문만으로는 주택임대차 계약 중 분쟁인지 알기 어렵습니다.",
  "suggested_categories": [],
  "clarification_question": "집주인과 다툰 이유가 월세 인상, 수리 거부, 계약갱신 거절, 중도해지 같은 문제인지 알려주세요."
}
""".strip()

    user_prompt = f"사용자 질문:\n{question}"

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0,
        )
    except Exception as exc:
        return {
            "source": "llm_failed",
            "scope": "ambiguous",
            "reason": str(exc),
            "suggested_categories": [],
            "clarification_question": "주택임대차 계약 중 어떤 문제인지 조금 더 구체적으로 알려주세요.",
        }

    raw_text = _extract_response_text(response)
    parsed = _extract_json_object(raw_text)
    clarification_question = parsed.get("clarification_question")
    if (
        not isinstance(clarification_question, str)
        or not clarification_question.strip()
    ):
        clarification_question = (
            "주택임대차 계약 중 어떤 문제인지 조금 더 구체적으로 알려주세요."
        )

    reason = parsed.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = "질문만으로는 B파트 범위인지 판단하기 어렵습니다."

    return {
        "source": "llm",
        "raw_text": raw_text,
        "scope": _normalize_scope(parsed.get("scope")),
        "reason": reason,
        "suggested_categories": _normalize_categories(
            parsed.get("suggested_categories")
        ),
        "clarification_question": clarification_question,
    }
