"""
B파트 RAG 검색 평가 스크립트.

test_questions.json의 질문을 한 번에 실행하고,
기대 카테고리가 Top-K 검색 결과에 포함되는지 확인합니다.

실행 위치:
    C:\\education\\ai-project\\Law-404\\backend

실행 예시:
    python ..\\backend\\data\\b_part\\evaluation\\run_search_eval.py
    python ..\\backend\\data\\b_part\\evaluation\\run_search_eval.py --use-category-filter
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
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_QUESTIONS_PATH = Path(__file__).resolve().parent / "test_questions.json"
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "search_test_results.json"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.rag.retrievers.b_part import BPartRetriever  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def summarize_result_categories(results: list[dict[str, Any]]) -> list[str]:
    return [str(result.get("category", "")) for result in results]


def simplify_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    simplified = []
    for rank, result in enumerate(results, start=1):
        simplified.append(
            {
                "rank": rank,
                "id": result.get("id"),
                "source_type": result.get("source_type"),
                "category": result.get("category"),
                "title": result.get("title"),
                "chunk_type": result.get("chunk_type"),
                "similarity": result.get("similarity"),
                "distance": result.get("distance"),
                "content_preview": str(result.get("content", ""))[:250],
                "metadata": result.get("metadata", {}),
            }
        )
    return simplified


def evaluate_questions(
    questions: list[dict[str, Any]],
    top_k: int,
    use_category_filter: bool,
) -> dict[str, Any]:
    retriever = BPartRetriever()
    evaluated = []

    for question_item in questions:
        question_id = question_item["id"]
        question = question_item["question"]
        expected_category = question_item["category"]
        category_filter = expected_category if use_category_filter else None

        results = retriever.search_sync(
            query=question,
            top_k=top_k,
            category=category_filter,
        )
        result_dicts = [result.to_dict() for result in results]
        top_categories = summarize_result_categories(result_dicts)
        expected_in_top_k = expected_category in top_categories
        top_1_category = top_categories[0] if top_categories else ""
        top_1_hit = top_1_category == expected_category
        similarities = [float(result.get("similarity", 0.0)) for result in result_dicts]

        evaluated.append(
            {
                "question_id": question_id,
                "question": question,
                "expected_category": expected_category,
                "category_filter": category_filter,
                "top_k": top_k,
                "expected_in_top_k": expected_in_top_k,
                "top_1_hit": top_1_hit,
                "top_1_category": top_1_category,
                "top_categories": top_categories,
                "average_similarity": mean(similarities) if similarities else 0.0,
                "max_similarity": max(similarities) if similarities else 0.0,
                "results": simplify_results(result_dicts),
            }
        )

    return build_report(evaluated, top_k, use_category_filter)


def build_report(
    evaluated: list[dict[str, Any]],
    top_k: int,
    use_category_filter: bool,
) -> dict[str, Any]:
    total = len(evaluated)
    top_k_hits = sum(1 for item in evaluated if item["expected_in_top_k"])
    top_1_hits = sum(1 for item in evaluated if item["top_1_hit"])
    all_average_similarities = [item["average_similarity"] for item in evaluated]
    all_max_similarities = [item["max_similarity"] for item in evaluated]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "top_k": top_k,
            "use_category_filter": use_category_filter,
        },
        "summary": {
            "total_questions": total,
            "top_k_hit_count": top_k_hits,
            "top_k_hit_rate": round(top_k_hits / total, 4) if total else 0.0,
            "top_1_hit_count": top_1_hits,
            "top_1_hit_rate": round(top_1_hits / total, 4) if total else 0.0,
            "average_similarity": round(mean(all_average_similarities), 4)
            if all_average_similarities
            else 0.0,
            "average_max_similarity": round(mean(all_max_similarities), 4)
            if all_max_similarities
            else 0.0,
        },
        "items": evaluated,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="B파트 RAG 검색 결과 일괄 평가")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--use-category-filter",
        action="store_true",
        help="각 질문의 expected category를 검색 필터로 사용합니다.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = read_json(args.questions)
    questions = payload.get("questions", [])

    if not questions:
        raise SystemExit("평가할 질문이 없습니다.")

    report = evaluate_questions(
        questions=questions,
        top_k=args.top_k,
        use_category_filter=args.use_category_filter,
    )
    write_json(args.output, report)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"결과 저장: {args.output}")


if __name__ == "__main__":
    main()
