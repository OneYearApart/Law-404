"""
B파트 LLM Context Resolver.

이 모듈은 최종 법률 답변을 생성하지 않습니다. 이전 대화와 현재 입력을 보고
현재 입력이 후속 답변인지, 실제로 처리해야 할 질문이 무엇인지, 지금 바로
최종 답변을 생성해도 되는지를 JSON으로 판단합니다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = os.getenv("B_PART_CONTEXT_MODEL", os.getenv("B_PART_LLM_MODEL", "gpt-4o"))

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

RESPONSE_MODES = {
    "final_answer",
    "ask_missing_info",
    "ambiguous",
    "out_of_scope",
    "action_confirmation",
    "action_result",
}


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


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_response_mode(value: Any) -> str:
    if isinstance(value, str) and value in RESPONSE_MODES:
        return value
    return "final_answer"


def analyze_b_part_context(
    current_message: str,
    history_text: str = "",
    fallback_question: str = "",
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """
    이전 대화와 현재 메시지를 바탕으로 실제 처리 질문과 응답 모드를 판단합니다.
    """
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return {
            "source": "llm_skipped",
            "reason": "OPENAI_API_KEY가 없습니다.",
            "is_followup": False,
            "resolved_question": fallback_question or current_message,
            "response_mode": "final_answer",
            "categories": [],
            "required_missing_questions": [],
            "optional_missing_questions": [],
            "tool_hints": [],
        }

    from openai import OpenAI

    system_prompt = """
당신은 한국 주택임대차 B파트 챗봇의 Context Resolver입니다.
법률 답변을 생성하지 말고, 반드시 JSON 객체 하나만 반환하세요.

B파트 범위:
- 주택임대차 계약 중 실제 거주 중 발생하는 분쟁
- 계약갱신, 계약갱신요구권, 묵시적갱신
- 차임증감, 전월세전환
- 임대인의무, 수선의무
- 계약해지, 계약 중 손해배상

역할:
1. 이전 대화와 현재 입력을 보고 현재 입력이 후속 답변인지 판단합니다.
2. 실제 처리해야 할 질문을 resolved_question으로 자연어 재작성합니다.
3. 필요한 카테고리를 고릅니다.
4. 아직 필수 정보가 부족하면 response_mode를 ask_missing_info로 설정합니다.
5. 필수 정보가 충분하면 response_mode를 final_answer로 설정합니다.

중요 규칙:
- "방금 말했잖아", "아까 말했듯", "1주일 지났다고" 같은 입력은 이전 대화의 후속 답변일 수 있습니다.
- "26년 10월 10일"은 보통 "2026년 10월 10일"로 해석하세요.
- 계약갱신/묵시적갱신 판단에서 계약 종료일이 없으면 필수 정보로 물어보세요.
- 월세 인상률 판단에서 현재 월세와 요구 월세가 없으면 필수 정보로 물어보세요.
- 수선의무 질문은 고장/하자 내용이 있으면 기본 답변은 가능하며, 증거 여부는 optional_missing_questions로 두세요.
- final_answer일 때도 optional_missing_questions는 넣을 수 있습니다.

반환 형식:
{
  "is_followup": true,
  "resolved_question": "보일러 고장으로 집주인에게 수리를 요청했지만 1주일이 지나도 수리하지 않는 상황입니다. 임대인의 수선의무와 대응 방법을 알고 싶습니다.",
  "response_mode": "final_answer",
  "categories": ["수선의무", "임대인의무"],
  "required_missing_questions": [],
  "optional_missing_questions": ["수리 요청을 문자나 카카오톡으로 남긴 증거가 있나요?"],
  "tool_hints": ["retriever"]
}
""".strip()

    user_prompt = (
        "이전 대화:\n"
        f"{history_text or '(이전 대화 없음)'}\n\n"
        "현재 사용자 입력:\n"
        f"{current_message}\n\n"
        "규칙 기반 fallback 질문:\n"
        f"{fallback_question or current_message}"
    )

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
            "reason": str(exc),
            "is_followup": False,
            "resolved_question": fallback_question or current_message,
            "response_mode": "final_answer",
            "categories": [],
            "required_missing_questions": [],
            "optional_missing_questions": [],
            "tool_hints": [],
        }

    raw_text = _extract_response_text(response)
    parsed = _extract_json_object(raw_text)
    resolved_question = parsed.get("resolved_question")
    if not isinstance(resolved_question, str) or not resolved_question.strip():
        resolved_question = fallback_question or current_message

    return {
        "source": "llm",
        "raw_text": raw_text,
        "is_followup": bool(parsed.get("is_followup")),
        "resolved_question": resolved_question.strip(),
        "response_mode": _normalize_response_mode(parsed.get("response_mode")),
        "categories": _normalize_categories(parsed.get("categories")),
        "required_missing_questions": _normalize_string_list(parsed.get("required_missing_questions")),
        "optional_missing_questions": _normalize_string_list(parsed.get("optional_missing_questions")),
        "tool_hints": _normalize_string_list(parsed.get("tool_hints")),
    }
