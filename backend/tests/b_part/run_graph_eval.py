"""
B파트 graph 통합 평가 스크립트.

Scope Checker, Intent Analyzer, Rule Engine, Calendar 후보 생성, RAG 검색이
기대대로 동작하는지 질문 세트를 기준으로 한 번에 확인합니다.

실행 위치:
    C:\\education\\ai-project\\Law-404

실행 예시:
    C:\\Users\\user\\anaconda3\\envs\\eduvenv\\python.exe backend\\data\\b_part\\evaluation\\run_graph_eval.py

일부만 실행:
    C:\\Users\\user\\anaconda3\\envs\\eduvenv\\python.exe backend\\data\\b_part\\evaluation\\run_graph_eval.py --limit 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_QUESTIONS_PATH = Path(__file__).resolve().parent / "graph_eval_questions.json"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "graph_eval_results.json"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.graph.parts.b_part.graph import graph  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def infer_actual_scope(final_state: dict[str, Any]) -> str:
    scope_result = final_state.get("scope_result")
    if isinstance(scope_result, dict):
        scope = scope_result.get("scope")
        if scope in {"in_scope", "out_of_scope", "ambiguous"}:
            return str(scope)

    retrieval_quality = final_state.get("retrieval_quality")
    if isinstance(retrieval_quality, dict):
        if retrieval_quality.get("is_out_of_scope"):
            return "out_of_scope"
        if retrieval_quality.get("is_ambiguous_scope"):
            return "ambiguous"

    return "in_scope"


def collect_rule_types(rule_results: list[dict[str, Any]]) -> list[str]:
    rule_types: list[str] = []
    for result in rule_results:
        for key in ("rule_type", "type", "name"):
            value = result.get(key)
            if isinstance(value, str) and value not in rule_types:
                rule_types.append(value)
                break
    return rule_types


def has_expected_category(
    actual_categories: list[str], expected_categories: list[str]
) -> bool:
    if not expected_categories:
        return True
    return any(category in actual_categories for category in expected_categories)


def has_expected_rule_type(
    actual_rule_types: list[str], expected_rule_types: list[str]
) -> bool:
    if not expected_rule_types:
        return True

    aliases = {
        "rent_increase": {"rent_increase", "rent_increase_limit"},
        "rent_increase_limit": {"rent_increase", "rent_increase_limit"},
        "renewal_request_period": {"renewal_request_period"},
    }
    actual_set = set(actual_rule_types)
    for expected_rule_type in expected_rule_types:
        accepted_values = aliases.get(expected_rule_type, {expected_rule_type})
        if actual_set & accepted_values:
            return True
    return False


def summarize_retrieved(retrieved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summarized: list[dict[str, Any]] = []
    for rank, document in enumerate(retrieved, start=1):
        summarized.append(
            {
                "rank": rank,
                "id": document.get("id"),
                "source_type": document.get("source_type"),
                "category": document.get("category"),
                "title": document.get("title"),
                "similarity": document.get("similarity"),
            }
        )
    return summarized


def evaluate_final_state(
    question_item: dict[str, Any],
    final_state: dict[str, Any],
) -> dict[str, Any]:
    expected_scope = question_item.get("expected_scope")
    expected_categories = question_item.get("expected_categories", [])
    expected_rule_types = question_item.get("expected_rule_types", [])
    expect_calendar_events = bool(question_item.get("expect_calendar_events"))
    expect_pending_action = bool(question_item.get("expect_pending_action"))

    actual_scope = infer_actual_scope(final_state)
    actual_categories = final_state.get("categories", [])
    if not isinstance(actual_categories, list):
        actual_categories = []

    rule_results = final_state.get("rule_results", [])
    if not isinstance(rule_results, list):
        rule_results = []
    actual_rule_types = collect_rule_types(rule_results)

    calendar_events = final_state.get("calendar_events", [])
    if not isinstance(calendar_events, list):
        calendar_events = []
    pending_action = final_state.get("pending_action")
    retrieved = final_state.get("retrieved", [])
    if not isinstance(retrieved, list):
        retrieved = []
    planner_result = final_state.get("planner_result")
    if not isinstance(planner_result, dict):
        planner_result = {}
    execution_plan = final_state.get("execution_plan")
    if not isinstance(execution_plan, dict):
        execution_plan = {}

    scope_hit = actual_scope == expected_scope
    category_hit = has_expected_category(actual_categories, expected_categories)
    rule_hit = has_expected_rule_type(actual_rule_types, expected_rule_types)
    calendar_hit = bool(calendar_events) == expect_calendar_events
    pending_action_hit = bool(pending_action) == expect_pending_action

    return {
        "id": question_item.get("id"),
        "group": question_item.get("group"),
        "question": question_item.get("question"),
        "expected": {
            "scope": expected_scope,
            "categories": expected_categories,
            "rule_types": expected_rule_types,
            "calendar_events": expect_calendar_events,
            "pending_action": expect_pending_action,
        },
        "actual": {
            "scope": actual_scope,
            "categories": actual_categories,
            "rule_types": actual_rule_types,
            "calendar_event_count": len(calendar_events),
            "has_pending_action": bool(pending_action),
            "retrieved_count": len(retrieved),
            "retrieval_quality": final_state.get("retrieval_quality"),
            "scope_result": final_state.get("scope_result"),
            "planner_result": planner_result,
            "execution_plan": execution_plan,
            "intent_result": final_state.get("intent_result"),
            "missing_questions": final_state.get("missing_questions", []),
            "retrieved": summarize_retrieved(retrieved),
            "final_answer_preview": str(final_state.get("final_answer", ""))[:500],
        },
        "checks": {
            "scope_hit": scope_hit,
            "category_hit": category_hit,
            "rule_hit": rule_hit,
            "calendar_hit": calendar_hit,
            "pending_action_hit": pending_action_hit,
            "passed": all(
                [
                    scope_hit,
                    category_hit,
                    rule_hit,
                    calendar_hit,
                    pending_action_hit,
                ]
            ),
        },
    }


async def run_case(question_item: dict[str, Any], top_k: int) -> dict[str, Any]:
    request = {
        "message": question_item["question"],
        "top_k": top_k,
    }

    try:
        final_state = await graph.ainvoke(request)
    except Exception as exc:
        return {
            "id": question_item.get("id"),
            "group": question_item.get("group"),
            "question": question_item.get("question"),
            "error": str(exc),
            "checks": {
                "passed": False,
            },
        }

    return evaluate_final_state(question_item=question_item, final_state=final_state)


def build_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    passed_items = [item for item in items if item.get("checks", {}).get("passed")]
    errored_items = [item for item in items if item.get("error")]

    def rate(key: str) -> float:
        values = [
            bool(item.get("checks", {}).get(key))
            for item in items
            if not item.get("error") and key in item.get("checks", {})
        ]
        return round(mean(values), 4) if values else 0.0

    group_summary: dict[str, dict[str, Any]] = {}
    for item in items:
        group = str(item.get("group") or "unknown")
        group_summary.setdefault(group, {"total": 0, "passed": 0})
        group_summary[group]["total"] += 1
        if item.get("checks", {}).get("passed"):
            group_summary[group]["passed"] += 1

    for value in group_summary.values():
        value["pass_rate"] = (
            round(value["passed"] / value["total"], 4) if value["total"] else 0.0
        )

    non_error_items = [item for item in items if not item.get("error")]
    retrieval_skipped_values: list[bool] = []
    retrieved_counts: list[int] = []
    tool_alignment_values: dict[str, list[bool]] = {
        "rule_engine": [],
        "retriever": [],
        "calendar_candidate": [],
    }

    for item in non_error_items:
        actual = item.get("actual", {})
        retrieval_quality = actual.get("retrieval_quality")
        if isinstance(retrieval_quality, dict):
            retrieval_skipped_values.append(bool(retrieval_quality.get("skipped")))

        retrieved_counts.append(int(actual.get("retrieved_count") or 0))

        planner_result = actual.get("planner_result")
        execution_plan = actual.get("execution_plan")
        if not isinstance(planner_result, dict) or not isinstance(execution_plan, dict):
            continue

        requested_tools = planner_result.get("tools_to_use")
        executed_tools = execution_plan.get("executed_tools")
        if not isinstance(requested_tools, list) or not isinstance(
            executed_tools, dict
        ):
            continue

        requested_set = {str(tool) for tool in requested_tools}
        for tool_name in tool_alignment_values:
            requested = tool_name in requested_set
            executed = bool(executed_tools.get(tool_name))
            tool_alignment_values[tool_name].append(requested == executed)

    def average_bool(values: list[bool]) -> float:
        return round(mean(values), 4) if values else 0.0

    return {
        "total_questions": total,
        "passed_count": len(passed_items),
        "failed_count": total - len(passed_items),
        "error_count": len(errored_items),
        "pass_rate": round(len(passed_items) / total, 4) if total else 0.0,
        "scope_hit_rate": rate("scope_hit"),
        "category_hit_rate": rate("category_hit"),
        "rule_hit_rate": rate("rule_hit"),
        "calendar_hit_rate": rate("calendar_hit"),
        "pending_action_hit_rate": rate("pending_action_hit"),
        "retrieval_skipped_rate": average_bool(retrieval_skipped_values),
        "average_retrieved_count": round(mean(retrieved_counts), 4)
        if retrieved_counts
        else 0.0,
        "tool_alignment": {
            tool_name: average_bool(values)
            for tool_name, values in tool_alignment_values.items()
        },
        "groups": group_summary,
    }


async def evaluate_questions(
    questions: list[dict[str, Any]],
    top_k: int,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for question_item in questions:
        print(f"평가 중: {question_item.get('id')} - {question_item.get('question')}")
        items.append(await run_case(question_item=question_item, top_k=top_k))

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "top_k": top_k,
        },
        "summary": build_summary(items),
        "items": items,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="B파트 graph 통합 평가")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--limit", type=int, default=0, help="앞에서 N개 질문만 평가합니다."
    )
    parser.add_argument("--group", default="", help="특정 group만 평가합니다.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = read_json(args.questions)
    questions = payload.get("questions", [])

    if args.group:
        questions = [item for item in questions if item.get("group") == args.group]
    if args.limit:
        questions = questions[: args.limit]
    if not questions:
        raise SystemExit("평가할 질문이 없습니다.")

    report = asyncio.run(evaluate_questions(questions=questions, top_k=args.top_k))
    write_json(args.output, report)

    print("\n[요약]")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"\n결과 저장: {args.output}")


if __name__ == "__main__":
    main()
