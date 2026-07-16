"""
B파트 보조 LLM Intent Analyzer.

기본 Intent Analyzer는 빠르고 예측 가능한 키워드/규칙 기반으로 동작합니다.
이 모듈은 그 규칙이 놓친 것 같은 질문에만 보조적으로 호출되어
카테고리와 Rule Engine 필요 여부를 JSON으로 판단합니다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = os.getenv("B_PART_INTENT_MODEL", os.getenv("B_PART_LLM_MODEL", "gpt-4o"))

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
    """
    LLM 응답에서 JSON 객체만 추출합니다.

    모델이 실수로 ```json 코드블록을 붙이더라도 최소한의 보정을 합니다.
    """
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


def analyze_b_part_intent(question: str, model: str = DEFAULT_MODEL) -> dict[str, Any]:
    """
    사용자 질문을 분석해 B파트 카테고리와 계산 필요 여부를 반환합니다.

    반환값은 항상 dict이며, OpenAI 호출/파싱 실패 시 {"source": "llm_failed"}를 반환합니다.
    """
    load_local_env()
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return {
            "source": "llm_skipped",
            "reason": "OPENAI_API_KEY가 없습니다.",
            "categories": [],
            "needs_rule_engine": False,
            "needs_calendar_events": False,
            "rule_targets": [],
        }

    from openai import OpenAI

    system_prompt = """
당신은 한국 주택임대차 B파트 질문 의도 분석기입니다.
답변은 반드시 JSON 객체 하나만 반환하세요.

허용 카테고리:
- 계약갱신
- 계약갱신요구권
- 묵시적갱신
- 차임증감
- 전월세전환
- 임대인의무
- 수선의무
- 계약해지
- 손해배상

규칙:
- 계약 종료일, 갱신, 언제부터, 일정, 캘린더, 등록 같은 표현이 있고 날짜가 있으면 계약갱신요구권/계약갱신 가능성이 높습니다.
- 월세/보증금 인상 금액 계산이 필요하면 rule_targets에 rent_increase를 넣으세요.
- 계약갱신요구권 행사 기간 계산이 필요하면 rule_targets에 renewal_request_period를 넣으세요.
- 캘린더 등록 후보가 필요하면 needs_calendar_events를 true로 설정하세요.
- 모르면 빈 배열과 false를 사용하세요.

반환 형식:
{
  "categories": ["계약갱신요구권"],
  "needs_rule_engine": true,
  "rule_targets": ["renewal_request_period"],
  "needs_calendar_events": true,
  "missing_fields": []
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
            "reason": str(exc),
            "categories": [],
            "needs_rule_engine": False,
            "needs_calendar_events": False,
            "rule_targets": [],
        }

    raw_text = _extract_response_text(response)
    parsed = _extract_json_object(raw_text)
    categories = _normalize_categories(parsed.get("categories"))
    rule_targets = parsed.get("rule_targets")
    if not isinstance(rule_targets, list):
        rule_targets = []

    missing_fields = parsed.get("missing_fields")
    if not isinstance(missing_fields, list):
        missing_fields = []

    return {
        "source": "llm",
        "raw_text": raw_text,
        "categories": categories,
        "needs_rule_engine": bool(parsed.get("needs_rule_engine")),
        "needs_calendar_events": bool(parsed.get("needs_calendar_events")),
        "rule_targets": [str(target) for target in rule_targets],
        "missing_fields": [str(field) for field in missing_fields],
    }
