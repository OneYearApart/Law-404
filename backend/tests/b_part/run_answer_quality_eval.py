"""
B파트 답변 품질 평가 스크립트.

최종 답변의 품질을 발표용으로 비교할 수 있도록 휴리스틱 지표를 계산합니다.
정답 채점기가 아니라, 개선 전/후 경향을 보기 위한 개발/발표용 평가 도구입니다.

실행 위치:
    C:\\education\\ai-project\\Law-404

실행:
    C:\\Users\\user\\anaconda3\\envs\\eduvenv\\python.exe backend\\data\\b_part\\evaluation\\run_answer_quality_eval.py --output backend\\data\\b_part\\evaluation\\answer_quality_eval_before.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_QUESTIONS_PATH = (
    Path(__file__).resolve().parent / "answer_quality_questions.json"
)
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "answer_quality_eval.json"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.graph.parts.b_part.graph import graph  # noqa: E402

REQUIRED_SECTIONS = [
    "① 결론",
    "② 쉬운 설명",
    "③ 법적 근거",
    "④ 관련 판례",
    "⑤ 추천 행동",
    "⑥ 주의사항",
    "⑦ 추가 확인 질문",
]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def count_additional_questions(answer: str) -> int:
    section_match = re.search(r"⑦\s*추가 확인 질문(?P<body>.*)", answer, re.DOTALL)
    if not section_match:
        return 0

    body = section_match.group("body")
    if "현재 추가 확인 질문은 없습니다" in body:
        return 0
    if "없습니다" in body[:80]:
        return 0

    question_marks = body.count("?")
    bullet_questions = len(
        re.findall(r"^\s*[-\d.]+\s+.*(?:\?|나요|세요|까요)", body, re.MULTILINE)
    )
    return max(question_marks, bullet_questions)


def has_law_basis(answer: str, retrieved: list[dict[str, Any]]) -> bool:
    has_law_doc = any(document.get("source_type") == "law" for document in retrieved)
    if not has_law_doc:
        return True
    return "제" in answer and any(
        keyword in answer for keyword in ["법", "민법", "주택임대차보호법", "시행령"]
    )


def has_unrelated_precedent_exposure(
    answer: str, retrieved: list[dict[str, Any]]
) -> bool:
    precedent_docs = [
        document for document in retrieved if document.get("source_type") == "precedent"
    ]
    if not precedent_docs:
        return False

    if "현재 검색 결과만으로는 직접 맞는 판례를 특정하기 어렵습니다" in answer:
        return False

    low_similarity_precedents = [
        document
        for document in precedent_docs
        if float(document.get("similarity") or 0) < 0.34
    ]
    return bool(low_similarity_precedents and "판례" in answer)


def has_required_format(answer: str) -> bool:
    return all(section in answer for section in REQUIRED_SECTIONS)


def has_calendar_format(answer: str, calendar_events: list[dict[str, Any]]) -> bool:
    if not calendar_events:
        return True
    return "캘린더 등록 가능 일정" in answer and "실제 등록 전" in answer


def evaluate_answer(
    final_state: dict[str, Any], question_item: dict[str, Any]
) -> dict[str, Any]:
    answer = str(final_state.get("final_answer", ""))
    retrieved = final_state.get("retrieved", [])
    if not isinstance(retrieved, list):
        retrieved = []
    calendar_events = final_state.get("calendar_events", [])
    if not isinstance(calendar_events, list):
        calendar_events = []
    rule_results = final_state.get("rule_results", [])
    if not isinstance(rule_results, list):
        rule_results = []
    planner_validation = final_state.get("planner_validation")
    if not isinstance(planner_validation, dict):
        planner_validation = {}

    expected_rule_min_count = int(question_item.get("expected_rule_min_count") or 0)
    expected_planner_decision = question_item.get(
        "expected_planner_validation_decision"
    )
    should_answer = bool(question_item.get("should_answer", True))

    additional_question_count = count_additional_questions(answer)
    law_basis = has_law_basis(answer, retrieved)
    unrelated_precedent = has_unrelated_precedent_exposure(answer, retrieved)
    format_ok = has_required_format(answer) if should_answer else True
    calendar_format_ok = has_calendar_format(answer, calendar_events)
    rule_result_hit = (
        len(rule_results) >= expected_rule_min_count
        if expected_rule_min_count
        else True
    )
    actual_planner_decision = planner_validation.get("decision")
    planner_decision_hit = (
        actual_planner_decision == expected_planner_decision
        if expected_planner_decision
        else True
    )
    answered_without_early_stop = len(retrieved) > 0 or len(rule_results) > 0
    answer_flow_hit = (
        answered_without_early_stop
        if should_answer
        else not answered_without_early_stop
    )

    return {
        "id": question_item.get("id"),
        "group": question_item.get("group"),
        "question": question_item.get("question"),
        "metrics": {
            "law_basis_included": law_basis,
            "unrelated_precedent_exposed": unrelated_precedent,
            "additional_question_count": additional_question_count,
            "additional_question_ok": additional_question_count <= 1,
            "format_ok": format_ok,
            "calendar_format_ok": calendar_format_ok,
            "rule_result_hit": rule_result_hit,
            "rule_result_count": len(rule_results),
            "expected_rule_min_count": expected_rule_min_count,
            "planner_validation_decision": actual_planner_decision,
            "expected_planner_validation_decision": expected_planner_decision,
            "planner_decision_hit": planner_decision_hit,
            "should_answer": should_answer,
            "answer_flow_hit": answer_flow_hit,
            "retrieved_count": len(retrieved),
            "law_doc_count": sum(
                1 for document in retrieved if document.get("source_type") == "law"
            ),
            "precedent_doc_count": sum(
                1
                for document in retrieved
                if document.get("source_type") == "precedent"
            ),
        },
        "state": {
            "categories": final_state.get("categories"),
            "retrieval_quality": final_state.get("retrieval_quality"),
            "planner_result": final_state.get("planner_result"),
            "planner_validation": planner_validation,
            "execution_plan": final_state.get("execution_plan"),
            "missing_questions": final_state.get("missing_questions"),
        },
        "answer_preview": answer[:1200],
    }


async def run_case(question_item: dict[str, Any], top_k: int) -> dict[str, Any]:
    try:
        final_state = await graph.ainvoke(
            {
                "message": question_item["question"],
                "top_k": top_k,
            }
        )
    except Exception as exc:
        return {
            "id": question_item.get("id"),
            "question": question_item.get("question"),
            "error": str(exc),
            "metrics": {
                "law_basis_included": False,
                "unrelated_precedent_exposed": True,
                "additional_question_count": 99,
                "additional_question_ok": False,
                "format_ok": False,
                "calendar_format_ok": False,
                "rule_result_hit": False,
                "rule_result_count": 0,
                "expected_rule_min_count": int(
                    question_item.get("expected_rule_min_count") or 0
                ),
                "planner_validation_decision": None,
                "expected_planner_validation_decision": question_item.get(
                    "expected_planner_validation_decision"
                ),
                "planner_decision_hit": False,
                "should_answer": bool(question_item.get("should_answer", True)),
                "answer_flow_hit": False,
            },
        }

    return evaluate_answer(final_state, question_item)


def build_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    valid_items = [item for item in items if not item.get("error")]
    metrics = [item.get("metrics", {}) for item in valid_items]

    def rate(key: str) -> float:
        values = [bool(metric.get(key)) for metric in metrics]
        return round(mean(values), 4) if values else 0.0

    additional_question_counts = [
        int(metric.get("additional_question_count") or 0) for metric in metrics
    ]

    return {
        "total_questions": len(items),
        "error_count": len(items) - len(valid_items),
        "law_basis_rate": rate("law_basis_included"),
        "unrelated_precedent_exposure_rate": rate("unrelated_precedent_exposed"),
        "additional_question_ok_rate": rate("additional_question_ok"),
        "average_additional_question_count": round(mean(additional_question_counts), 4)
        if additional_question_counts
        else 0.0,
        "format_ok_rate": rate("format_ok"),
        "calendar_format_ok_rate": rate("calendar_format_ok"),
        "rule_result_hit_rate": rate("rule_result_hit"),
        "planner_decision_hit_rate": rate("planner_decision_hit"),
        "answer_flow_hit_rate": rate("answer_flow_hit"),
    }


async def evaluate_questions(
    questions: list[dict[str, Any]], top_k: int
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for question_item in questions:
        print(f"평가 중: {question_item.get('id')} - {question_item.get('question')}")
        items.append(await run_case(question_item, top_k=top_k))

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "summary": build_summary(items),
        "items": items,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="B파트 답변 품질 평가")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--top-k", type=int, default=5)
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
    if not questions:
        raise SystemExit("평가할 질문이 없습니다.")

    report = asyncio.run(evaluate_questions(questions=questions, top_k=args.top_k))
    write_json(args.output, report)

    print("\n[요약]")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"\n결과 저장: {args.output}")


if __name__ == "__main__":
    main()
