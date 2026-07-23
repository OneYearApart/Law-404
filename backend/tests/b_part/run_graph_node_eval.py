"""
B파트 LangGraph 노드 흐름 회귀 평가 스크립트.

이 스크립트는 답변 문장 자체보다 LangGraph 각 단계가 의도한 흐름으로
동작하는지 확인합니다.

확인 대상:
- 정보 부족 질문은 retrieve 전에 멈추는지
- 범위 밖 질문은 retrieve 없이 종료되는지
- 날짜가 충분한 질문은 Rule Engine, Retriever, Answer까지 진행되는지
- 캘린더 승인 메시지는 Calendar registration 준비 상태로 종료되는지
- 2턴 대화에서 이전 질문 맥락이 유지되는지

실행 위치:
    C:\\education\\ai-project\\Law-404

실행 예시:
    C:\\Users\\user\\anaconda3\\envs\\eduvenv\\python.exe backend\\data\\b_part\\evaluation\\run_graph_node_eval.py
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
DEFAULT_QUESTIONS_PATH = (
    Path(__file__).resolve().parent / "graph_node_eval_questions.json"
)
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "graph_node_eval_results.json"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.graph.parts.b_part.graph import graph  # noqa: E402
from app.graph.parts.b_part.memory import memory_store  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def collect_rule_contract_end_dates(rule_results: list[dict[str, Any]]) -> list[str]:
    dates: list[str] = []
    for rule_result in rule_results:
        value = rule_result.get("contract_end_date")
        if isinstance(value, str) and value not in dates:
            dates.append(value)
    return dates


def extract_actual(final_state: dict[str, Any]) -> dict[str, Any]:
    retrieved = final_state.get("retrieved", [])
    if not isinstance(retrieved, list):
        retrieved = []

    rule_results = final_state.get("rule_results", [])
    if not isinstance(rule_results, list):
        rule_results = []

    calendar_events = final_state.get("calendar_events", [])
    if not isinstance(calendar_events, list):
        calendar_events = []

    retrieval_quality = final_state.get("retrieval_quality")
    if not isinstance(retrieval_quality, dict):
        retrieval_quality = {}

    scope_result = final_state.get("scope_result")
    if not isinstance(scope_result, dict):
        scope_result = {}

    planner_validation = final_state.get("planner_validation")
    if not isinstance(planner_validation, dict):
        planner_validation = {}

    pending_action = final_state.get("pending_action")
    if not isinstance(pending_action, dict):
        pending_action = {}

    calendar_registration = final_state.get("calendar_registration")
    if not isinstance(calendar_registration, dict):
        calendar_registration = {}
    calendar_tool_result = final_state.get("calendar_tool_result")
    if not isinstance(calendar_tool_result, dict):
        calendar_tool_result = {}
    executed_tools = final_state.get("executed_tools", [])
    if not isinstance(executed_tools, list):
        executed_tools = []
    skipped_tools = final_state.get("skipped_tools", [])
    if not isinstance(skipped_tools, list):
        skipped_tools = []

    return {
        "categories": final_state.get("categories", []),
        "executed_tools": executed_tools,
        "skipped_tools": skipped_tools,
        "retrieved_count": len(retrieved),
        "rule_count": len(rule_results),
        "calendar_event_count": len(calendar_events),
        "retrieval_reason": retrieval_quality.get("reason"),
        "retrieval_is_weak": retrieval_quality.get("is_weak"),
        "retrieval_refined_by_llm": retrieval_quality.get("refined_by_llm"),
        "scope": scope_result.get("scope"),
        "planner_validation_decision": planner_validation.get("decision"),
        "pending_action_type": pending_action.get("type"),
        "calendar_registration_status": calendar_registration.get("status"),
        "calendar_tool_status": calendar_tool_result.get("status"),
        "calendar_tool_event_count": calendar_tool_result.get("event_count"),
        "contract_end_dates": collect_rule_contract_end_dates(rule_results),
        "final_answer_preview": str(final_state.get("final_answer", ""))[:300],
    }


def check_expectations(
    actual: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    checks: dict[str, bool] = {}

    if "retrieved_count" in expected:
        checks["retrieved_count"] = (
            actual["retrieved_count"] == expected["retrieved_count"]
        )
    if "retrieved_min_count" in expected:
        checks["retrieved_min_count"] = (
            actual["retrieved_count"] >= expected["retrieved_min_count"]
        )
    if "rule_min_count" in expected:
        checks["rule_min_count"] = actual["rule_count"] >= expected["rule_min_count"]
    if "calendar_event_min_count" in expected:
        checks["calendar_event_min_count"] = (
            actual["calendar_event_count"] >= expected["calendar_event_min_count"]
        )
    if "retrieval_reason" in expected:
        checks["retrieval_reason"] = (
            actual["retrieval_reason"] == expected["retrieval_reason"]
        )
    if "scope" in expected:
        checks["scope"] = actual["scope"] == expected["scope"]
    if "planner_validation_decision" in expected:
        checks["planner_validation_decision"] = (
            actual["planner_validation_decision"]
            == expected["planner_validation_decision"]
        )
    if "executed_tools_include" in expected:
        expected_tools = expected["executed_tools_include"]
        checks["executed_tools_include"] = all(
            tool in actual["executed_tools"] for tool in expected_tools
        )
    if "skipped_tools_include" in expected:
        expected_tools = expected["skipped_tools_include"]
        checks["skipped_tools_include"] = all(
            tool in actual["skipped_tools"] for tool in expected_tools
        )
    if "pending_action_type" in expected:
        checks["pending_action_type"] = (
            actual["pending_action_type"] == expected["pending_action_type"]
        )
    if "calendar_registration_status" in expected:
        checks["calendar_registration_status"] = (
            actual["calendar_registration_status"]
            == expected["calendar_registration_status"]
        )
    if "calendar_tool_status" in expected:
        checks["calendar_tool_status"] = (
            actual["calendar_tool_status"] == expected["calendar_tool_status"]
        )
    if "calendar_tool_event_count" in expected:
        checks["calendar_tool_event_count"] = (
            actual["calendar_tool_event_count"] == expected["calendar_tool_event_count"]
        )
    if "contract_end_date" in expected:
        checks["contract_end_date"] = (
            expected["contract_end_date"] in actual["contract_end_dates"]
        )

    return {
        "items": checks,
        "passed": all(checks.values()) if checks else True,
    }


async def run_single_case(case: dict[str, Any], top_k: int) -> dict[str, Any]:
    request: dict[str, Any] = {
        "message": case["question"],
        "conversation_id": f"node-eval-{case['id']}",
        "top_k": top_k,
    }
    if isinstance(case.get("pending_action"), dict):
        request["pending_action"] = case["pending_action"]
    for key in ("calendar_mode", "calendar_provider", "calendar_id"):
        if key in case:
            request[key] = case[key]

    try:
        final_state = await graph.ainvoke(request)
    except Exception as exc:
        return {
            "id": case.get("id"),
            "group": case.get("group"),
            "question": case.get("question"),
            "error": str(exc),
            "checks": {"items": {}, "passed": False},
        }

    actual = extract_actual(final_state)
    return {
        "id": case.get("id"),
        "group": case.get("group"),
        "question": case.get("question"),
        "expected": case.get("expected", {}),
        "actual": actual,
        "checks": check_expectations(actual, case.get("expected", {})),
    }


async def run_multi_turn_case(case: dict[str, Any], top_k: int) -> dict[str, Any]:
    conversation_id = f"node-eval-{case['id']}"
    memory_store.clear(conversation_id)

    turn_results: list[dict[str, Any]] = []
    for index, turn in enumerate(case.get("turns", []), start=1):
        request = {
            "message": turn["message"],
            "conversation_id": conversation_id,
            "top_k": top_k,
        }
        try:
            final_state = await graph.ainvoke(request)
        except Exception as exc:
            turn_results.append(
                {
                    "turn": index,
                    "message": turn.get("message"),
                    "error": str(exc),
                    "checks": {"items": {}, "passed": False},
                }
            )
            continue

        actual = extract_actual(final_state)
        turn_results.append(
            {
                "turn": index,
                "message": turn.get("message"),
                "expected": turn.get("expected", {}),
                "actual": actual,
                "checks": check_expectations(actual, turn.get("expected", {})),
            }
        )

    return {
        "id": case.get("id"),
        "group": case.get("group"),
        "turns": turn_results,
        "checks": {
            "passed": all(turn.get("checks", {}).get("passed") for turn in turn_results)
            if turn_results
            else False
        },
    }


def build_summary(
    single_results: list[dict[str, Any]], multi_results: list[dict[str, Any]]
) -> dict[str, Any]:
    single_passes = [
        bool(result.get("checks", {}).get("passed")) for result in single_results
    ]
    multi_passes = [
        bool(result.get("checks", {}).get("passed")) for result in multi_results
    ]

    all_passes = single_passes + multi_passes
    missing_stop_results = [
        result
        for result in single_results
        if result.get("group") in {"missing_scope", "keyword_scope"}
    ]
    missing_stop_hits = [
        result.get("actual", {}).get("retrieved_count") == 0
        for result in missing_stop_results
    ]

    return {
        "total_cases": len(all_passes),
        "single_turn_cases": len(single_results),
        "multi_turn_cases": len(multi_results),
        "pass_rate": round(mean(all_passes), 4) if all_passes else 0.0,
        "single_turn_pass_rate": round(mean(single_passes), 4)
        if single_passes
        else 0.0,
        "multi_turn_pass_rate": round(mean(multi_passes), 4) if multi_passes else 0.0,
        "pre_retrieval_stop_rate": round(mean(missing_stop_hits), 4)
        if missing_stop_hits
        else 0.0,
    }


async def evaluate(payload: dict[str, Any], top_k: int) -> dict[str, Any]:
    single_results: list[dict[str, Any]] = []
    for case in payload.get("single_turn", []):
        print(f"단일턴 평가 중: {case.get('id')} - {case.get('question')}")
        single_results.append(await run_single_case(case, top_k=top_k))

    multi_results: list[dict[str, Any]] = []
    for case in payload.get("multi_turn", []):
        print(f"멀티턴 평가 중: {case.get('id')}")
        multi_results.append(await run_multi_turn_case(case, top_k=top_k))

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": build_summary(single_results, multi_results),
        "single_turn": single_results,
        "multi_turn": multi_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="B파트 LangGraph 노드 흐름 평가")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--top-k", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = read_json(args.questions)
    result = asyncio.run(evaluate(payload, top_k=args.top_k))
    write_json(args.output, result)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"결과 저장: {args.output}")


if __name__ == "__main__":
    main()
