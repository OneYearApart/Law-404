"""
B파트 평가 결과 JSON을 비교해 발표용 Markdown 리포트를 생성합니다.

사용 예시:
    C:\\Users\\user\\anaconda3\\envs\\eduvenv\\python.exe backend\\data\\b_part\\evaluation\\compare_eval_reports.py
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


EVALUATION_DIR = Path(__file__).resolve().parent
DEFAULT_BEFORE_PATH = EVALUATION_DIR / "answer_quality_eval_before_response_refine.json"
DEFAULT_AFTER_PATH = EVALUATION_DIR / "answer_quality_eval_after_validator.json"
DEFAULT_GRAPH_PATH = EVALUATION_DIR / "graph_node_eval_results.json"
DEFAULT_OUTPUT_PATH = EVALUATION_DIR / "b_part_eval_comparison_report.md"

SUMMARY_METRICS = [
    ("law_basis_rate", "법령 근거 포함률"),
    ("unrelated_precedent_exposure_rate", "관련 없는 판례 노출률"),
    ("additional_question_ok_rate", "추가 질문 1개 이하 비율"),
    ("average_additional_question_count", "평균 추가 질문 수"),
    ("format_ok_rate", "응답 형식 준수율"),
    ("calendar_format_ok_rate", "캘린더 안내 형식 준수율"),
    ("rule_result_hit_rate", "Rule Engine 결과 반영률"),
    ("planner_decision_hit_rate", "Planner Validator 결정 적중률"),
    ("answer_flow_hit_rate", "답변 흐름 제어 적중률"),
]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, int):
        return str(value)
    return str(value)


def format_delta(before: Any, after: Any) -> str:
    if not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return "-"
    delta = after - before
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:.4f}"


def build_metric_table(before_summary: dict[str, Any], after_summary: dict[str, Any]) -> str:
    lines = [
        "| 지표 | 개선 전 | 개선 후 | 변화 |",
        "|---|---:|---:|---:|",
    ]
    for key, label in SUMMARY_METRICS:
        before_value = before_summary.get(key)
        after_value = after_summary.get(key)
        lines.append(
            "| {label} | {before} | {after} | {delta} |".format(
                label=label,
                before=format_value(before_value),
                after=format_value(after_value),
                delta=format_delta(before_value, after_value),
            )
        )
    return "\n".join(lines)


def index_items(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    items = report.get("items", [])
    if not isinstance(items, list):
        return {}
    return {
        str(item.get("id")): item
        for item in items
        if isinstance(item, dict) and item.get("id")
    }


def get_metric(item: dict[str, Any] | None, key: str) -> Any:
    if not item:
        return None
    metrics = item.get("metrics", {})
    if not isinstance(metrics, dict):
        return None
    return metrics.get(key)


def build_case_table(before_report: dict[str, Any], after_report: dict[str, Any]) -> str:
    before_items = index_items(before_report)
    after_items = index_items(after_report)
    all_ids = sorted(set(before_items) | set(after_items))

    rows = [
        "| 케이스 | 개선 전 흐름 | 개선 후 흐름 | 개선 전 형식 | 개선 후 형식 |",
        "|---|---:|---:|---:|---:|",
    ]
    for item_id in all_ids:
        before_item = before_items.get(item_id)
        after_item = after_items.get(item_id)
        before_flow = get_metric(before_item, "answer_flow_hit")
        after_flow = get_metric(after_item, "answer_flow_hit")
        before_format = get_metric(before_item, "format_ok")
        after_format = get_metric(after_item, "format_ok")

        if before_flow is None and after_flow is None and before_format == after_format:
            continue

        rows.append(
            "| {item_id} | {before_flow} | {after_flow} | {before_format} | {after_format} |".format(
                item_id=item_id,
                before_flow=format_value(before_flow),
                after_flow=format_value(after_flow),
                before_format=format_value(before_format),
                after_format=format_value(after_format),
            )
        )

    if len(rows) == 2:
        rows.append("| - | - | - | - | - |")
    return "\n".join(rows)


def build_graph_summary(graph_report: dict[str, Any] | None) -> str:
    if not graph_report:
        return "- LangGraph 노드 회귀 평가 결과 파일이 없습니다."

    summary = graph_report.get("summary", {})
    if not isinstance(summary, dict):
        return "- LangGraph 노드 회귀 평가 summary가 없습니다."

    return "\n".join(
        [
            "| 지표 | 값 |",
            "|---|---:|",
            f"| 전체 케이스 수 | {format_value(summary.get('total_cases'))} |",
            f"| 전체 통과율 | {format_value(summary.get('pass_rate'))} |",
            f"| 단일턴 통과율 | {format_value(summary.get('single_turn_pass_rate'))} |",
            f"| 멀티턴 통과율 | {format_value(summary.get('multi_turn_pass_rate'))} |",
            f"| 검색 전 차단율 | {format_value(summary.get('pre_retrieval_stop_rate'))} |",
        ]
    )


def build_report(
    *,
    before_path: Path,
    after_path: Path,
    graph_path: Path | None,
) -> str:
    before_report = read_json(before_path)
    after_report = read_json(after_path)
    graph_report = read_json(graph_path) if graph_path and graph_path.exists() else None

    before_summary = before_report.get("summary", {})
    after_summary = after_report.get("summary", {})

    lines = [
        "# B파트 RAG 답변 품질 개선 비교 리포트",
        "",
        f"- 생성 시각: {datetime.now().isoformat(timespec='seconds')}",
        f"- 개선 전 파일: `{before_path.name}`",
        f"- 개선 후 파일: `{after_path.name}`",
        "",
        "## 1. 응답 품질 지표 변화",
        "",
        build_metric_table(before_summary, after_summary),
        "",
        "## 2. 케이스별 주요 변화",
        "",
        build_case_table(before_report, after_report),
        "",
        "## 3. LangGraph 노드 회귀 평가",
        "",
        build_graph_summary(graph_report),
        "",
        "## 4. 발표용 요약",
        "",
        "- Planner Validator를 도입해 LLM Planner가 판단한 부족 정보를 실행 전에 한 번 더 검증했습니다.",
        "- 필수 정보가 부족한 질문은 검색 전에 멈추고, 답변 가능한 질문은 Rule/RAG 단계로 진행하도록 분리했습니다.",
        "- 답변 흐름 제어와 Planner Validator 판단을 별도 지표로 측정할 수 있게 만들었습니다.",
        "- LangGraph 노드 회귀 평가를 통해 정보 부족/범위 밖/캘린더 승인/멀티턴 흐름이 유지되는지 확인했습니다.",
    ]
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="B파트 평가 결과 비교 리포트 생성")
    parser.add_argument("--before", type=Path, default=DEFAULT_BEFORE_PATH)
    parser.add_argument("--after", type=Path, default=DEFAULT_AFTER_PATH)
    parser.add_argument("--graph", type=Path, default=DEFAULT_GRAPH_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_report(
        before_path=args.before,
        after_path=args.after,
        graph_path=args.graph,
    )
    write_text(args.output, report)
    print(f"비교 리포트 저장: {args.output}")


if __name__ == "__main__":
    main()
