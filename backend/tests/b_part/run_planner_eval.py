"""
B파트 Intent Planner 평가 스크립트.

키워드 기반 카테고리 분류와 LLM Planner 카테고리 분류를 같은 질문 세트로 비교합니다.
발표 자료에서 "개선 전/후" 수치로 사용할 수 있도록 hit rate와 delta를 JSON으로 저장합니다.

실행 위치:
    C:\\education\\ai-project\\Law-404

실행:
    C:\\Users\\user\\anaconda3\\envs\\eduvenv\\python.exe backend\\data\\b_part\\evaluation\\run_planner_eval.py

일부만 실행:
    C:\\Users\\user\\anaconda3\\envs\\eduvenv\\python.exe backend\\data\\b_part\\evaluation\\run_planner_eval.py --limit 3
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_QUESTIONS_PATH = Path(__file__).resolve().parent / "test_questions.json"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "planner_eval_results.json"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.graph.parts.b_part.graph import detect_categories  # noqa: E402
from app.llm.b_part_planner import analyze_b_part_plan  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def has_expected_category(actual_categories: list[str], expected_category: str) -> bool:
    return expected_category in actual_categories


def evaluate_question(question_item: dict[str, Any]) -> dict[str, Any]:
    question = str(question_item["question"])
    expected_category = str(question_item["category"])

    keyword_categories = detect_categories(question)
    planner_result = analyze_b_part_plan(
        current_message=question,
        resolved_question=question,
        history_text="",
        context_result={},
        keyword_categories=keyword_categories,
    )
    planner_categories = planner_result.get("categories", [])
    if not isinstance(planner_categories, list):
        planner_categories = []

    keyword_hit = has_expected_category(keyword_categories, expected_category)
    planner_hit = has_expected_category(planner_categories, expected_category)

    return {
        "id": question_item.get("id"),
        "question": question,
        "expected_category": expected_category,
        "keyword": {
            "categories": keyword_categories,
            "hit": keyword_hit,
        },
        "planner": {
            "scope": planner_result.get("scope"),
            "intent": planner_result.get("intent"),
            "categories": planner_categories,
            "known_facts": planner_result.get("known_facts"),
            "missing_required_facts": planner_result.get("missing_required_facts"),
            "missing_optional_facts": planner_result.get("missing_optional_facts"),
            "tools_to_use": planner_result.get("tools_to_use"),
            "answer_mode": planner_result.get("answer_mode"),
            "reason": planner_result.get("reason"),
            "source": planner_result.get("source"),
            "hit": planner_hit,
        },
        "comparison": {
            "improved": planner_hit and not keyword_hit,
            "regressed": keyword_hit and not planner_hit,
            "same": keyword_hit == planner_hit,
        },
    }


def build_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    keyword_hits = [bool(item["keyword"]["hit"]) for item in items]
    planner_hits = [bool(item["planner"]["hit"]) for item in items]
    improved = [item for item in items if item["comparison"]["improved"]]
    regressed = [item for item in items if item["comparison"]["regressed"]]

    keyword_hit_rate = round(mean(keyword_hits), 4) if keyword_hits else 0.0
    planner_hit_rate = round(mean(planner_hits), 4) if planner_hits else 0.0

    return {
        "total_questions": total,
        "keyword_hit_count": sum(keyword_hits),
        "keyword_hit_rate": keyword_hit_rate,
        "planner_hit_count": sum(planner_hits),
        "planner_hit_rate": planner_hit_rate,
        "hit_rate_delta": round(planner_hit_rate - keyword_hit_rate, 4),
        "improved_count": len(improved),
        "regressed_count": len(regressed),
        "improved_question_ids": [item["id"] for item in improved],
        "regressed_question_ids": [item["id"] for item in regressed],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = read_json(args.questions)
    questions = payload.get("questions", [])
    if not isinstance(questions, list):
        raise ValueError("questions 필드는 리스트여야 합니다.")
    if args.limit > 0:
        questions = questions[: args.limit]

    items: list[dict[str, Any]] = []
    for question_item in questions:
        print(f"평가 중: {question_item.get('id')} - {question_item.get('question')}")
        items.append(evaluate_question(question_item))

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "description": "B파트 키워드 기반 분류와 LLM Intent Planner 분류 비교",
        "summary": build_summary(items),
        "items": items,
    }
    write_json(args.output, result)

    print("\n평가 완료")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"\n결과 파일: {args.output}")


if __name__ == "__main__":
    main()
