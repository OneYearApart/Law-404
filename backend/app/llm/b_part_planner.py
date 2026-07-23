"""
B파트 LLM Intent Planner.

Context Resolver가 "이전 대화와 현재 입력을 합쳐 실제 질문을 만드는 역할"이라면,
Planner는 그 질문을 처리하기 위해 어떤 범위/카테고리/도구/부족 정보가 필요한지
구조화된 JSON으로 계획합니다.

이 모듈은 최종 법률 답변을 생성하지 않습니다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = os.getenv(
    "B_PART_PLANNER_MODEL", os.getenv("B_PART_LLM_MODEL", "gpt-4o")
)

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

SCOPES = {"in_scope", "out_of_scope", "ambiguous"}
ANSWER_MODES = {
    "final_answer",
    "ask_missing_info",
    "out_of_scope",
    "ambiguous",
    "action_confirmation",
}
TOOLS = {"rule_engine", "retriever", "calendar_candidate", "scope_checker"}
INTENTS = {
    "renewal",
    "renewal_request",
    "tacit_renewal",
    "rent_increase",
    "rent_conversion",
    "landlord_duty",
    "repair_duty",
    "termination",
    "damages",
    "out_of_scope",
    "ambiguous",
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


def _normalize_string(value: Any, allowed: set[str], default: str) -> str:
    if isinstance(value, str) and value in allowed:
        return value
    return default


def _normalize_string_list(value: Any, allowed: set[str] | None = None) -> list[str]:
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        if allowed is not None and text not in allowed:
            continue
        if text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def analyze_b_part_plan(
    current_message: str,
    resolved_question: str,
    history_text: str = "",
    context_result: dict[str, Any] | None = None,
    keyword_categories: list[str] | None = None,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """
    사용자 질문 처리 계획을 구조화해 반환합니다.

    실패해도 graph가 기존 규칙 기반 흐름으로 동작할 수 있도록 항상 dict를 반환합니다.
    """
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return {
            "source": "llm_skipped",
            "reason": "OPENAI_API_KEY가 없습니다.",
            "scope": "ambiguous",
            "intent": "ambiguous",
            "categories": [],
            "known_facts": {},
            "missing_required_facts": [],
            "missing_optional_facts": [],
            "tools_to_use": [],
            "answer_mode": "final_answer",
        }

    from openai import OpenAI

    system_prompt = """
당신은 한국 주택임대차 B파트 챗봇의 Intent Planner입니다.
최종 법률 답변을 작성하지 말고, 반드시 JSON 객체 하나만 반환하세요.

B파트 범위:
- 주택임대차 계약 체결 이후 실제 거주 중 발생하는 계약 중 분쟁
- 계약갱신, 계약갱신요구권, 묵시적갱신
- 차임증감, 전월세전환
- 임대인의무, 수선의무
- 계약해지, 계약 중 손해배상

제외 범위:
- 계약 전 전세사기/등기부/권리분석
- 계약 종료 후 보증금 반환/임차권등기명령/경매/배당/명도/원상회복
- 상가, 점포, 토지, 공장 등 비주택 임대차

허용 카테고리:
계약갱신, 계약갱신요구권, 묵시적갱신, 차임증감, 전월세전환, 임대인의무, 수선의무, 계약해지, 손해배상

허용 intent:
renewal, renewal_request, tacit_renewal, rent_increase, rent_conversion,
landlord_duty, repair_duty, termination, damages, out_of_scope, ambiguous

허용 tools_to_use:
rule_engine, retriever, calendar_candidate, scope_checker

판단 규칙:
- 날짜/금액 계산은 LLM이 직접 계산하지 말고 rule_engine 필요 여부만 판단하세요.
- 법령/판례 근거가 필요한 일반 법률 답변은 retriever를 포함하세요.
- 계약 종료일이 있고 갱신요구 기간 또는 캘린더 일정이 필요하면 rule_engine과 calendar_candidate를 포함하세요.
- 월세 인상률 또는 5% 초과 여부가 필요하면 rule_engine을 포함하세요.
- 집주인이 "직접 거주", "실거주", "들어와 산다", "나가달라"고 말한 상황은 단순 계약해지가 아니라
  계약갱신요구권/갱신거절 문제로 우선 분류하세요.
- 수선의무 질문은 하자 내용이 있으면 final_answer가 가능하며, 증거 여부는 optional로 둘 수 있습니다.
- 필수 정보가 없어서 답변하면 안 되는 경우에만 answer_mode를 ask_missing_info로 두세요.
- scope가 out_of_scope면 intent도 out_of_scope로 두세요.

반환 형식:
{
  "scope": "in_scope",
  "intent": "repair_duty",
  "categories": ["수선의무", "임대인의무"],
  "known_facts": {
    "defect": "보일러 고장",
    "repair_delay": "1주일"
  },
  "missing_required_facts": [],
  "missing_optional_facts": ["repair_evidence"],
  "tools_to_use": ["retriever"],
  "answer_mode": "final_answer",
  "reason": "보일러 수리 지연은 임대인의 수선의무 문제입니다."
}
""".strip()

    user_prompt = (
        "이전 대화:\n"
        f"{history_text or '(이전 대화 없음)'}\n\n"
        "현재 사용자 입력:\n"
        f"{current_message}\n\n"
        "Context Resolver가 정리한 실제 처리 질문:\n"
        f"{resolved_question}\n\n"
        "Context Resolver 결과:\n"
        f"{json.dumps(context_result or {}, ensure_ascii=False)}\n\n"
        "키워드 기반 카테고리 후보:\n"
        f"{json.dumps(keyword_categories or [], ensure_ascii=False)}"
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
            "scope": "ambiguous",
            "intent": "ambiguous",
            "categories": [],
            "known_facts": {},
            "missing_required_facts": [],
            "missing_optional_facts": [],
            "tools_to_use": [],
            "answer_mode": "final_answer",
        }

    raw_text = _extract_response_text(response)
    parsed = _extract_json_object(raw_text)

    return {
        "source": "llm",
        "raw_text": raw_text,
        "scope": _normalize_string(parsed.get("scope"), SCOPES, "ambiguous"),
        "intent": _normalize_string(parsed.get("intent"), INTENTS, "ambiguous"),
        "categories": _normalize_string_list(
            parsed.get("categories"), B_PART_CATEGORIES
        ),
        "known_facts": _normalize_dict(parsed.get("known_facts")),
        "missing_required_facts": _normalize_string_list(
            parsed.get("missing_required_facts")
        ),
        "missing_optional_facts": _normalize_string_list(
            parsed.get("missing_optional_facts")
        ),
        "tools_to_use": _normalize_string_list(parsed.get("tools_to_use"), TOOLS),
        "answer_mode": _normalize_string(
            parsed.get("answer_mode"), ANSWER_MODES, "final_answer"
        ),
        "reason": str(parsed.get("reason") or "").strip(),
    }
