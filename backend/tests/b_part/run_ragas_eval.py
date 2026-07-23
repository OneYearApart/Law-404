"""
B파트 RAGAS 평가 스크립트.

이 스크립트는 B파트 graph를 실제로 실행한 뒤 RAGAS 평가 입력을 구성합니다.

평가 입력 매핑:
    user_input = 사용자 질문
    response = B파트 최종 답변
    retrieved_contexts = Retriever가 반환한 법령/판례 chunk content 목록
    reference = 사람이 작성한 기준 답변

실행 위치:
    C:\\education\\ai-project\\Law-404

실행 예시:
    C:\\Users\\user\\anaconda3\\envs\\eduvenv\\python.exe backend\\data\\b_part\\evaluation\\run_ragas_eval.py --limit 3

주의:
    RAGAS는 별도 의존성입니다. 설치되어 있지 않으면 아래 명령을 먼저 실행하세요.
    pip install ragas
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_QUESTIONS_PATH = (
    Path(__file__).resolve().parent / "ragas_reference_questions.json"
)
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "ragas_eval_results.json"
DEFAULT_METRICS = [
    "faithfulness",
    "answer_relevancy",
    "answer_correctness",
    "context_precision",
    "context_recall",
]

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


def get_retrieved_contexts(final_state: dict[str, Any], max_contexts: int) -> list[str]:
    retrieved = final_state.get("retrieved", [])
    if not isinstance(retrieved, list):
        return []

    contexts: list[str] = []
    for document in retrieved[:max_contexts]:
        if not isinstance(document, dict):
            continue
        content = str(document.get("content") or "").strip()
        if content:
            contexts.append(content)
    return contexts


def summarize_retrieved(final_state: dict[str, Any]) -> list[dict[str, Any]]:
    retrieved = final_state.get("retrieved", [])
    if not isinstance(retrieved, list):
        return []

    summary: list[dict[str, Any]] = []
    for rank, document in enumerate(retrieved, start=1):
        if not isinstance(document, dict):
            continue
        summary.append(
            {
                "rank": rank,
                "id": document.get("id"),
                "source_type": document.get("source_type"),
                "category": document.get("category"),
                "title": document.get("title"),
                "chunk_type": document.get("chunk_type"),
                "similarity": document.get("similarity"),
            }
        )
    return summary


def load_ragas_metric_objects(metric_names: list[str]):
    """
    RAGAS metric 객체를 생성합니다.

    RAGAS는 버전별로 metric import 경로가 바뀐 적이 있어서
    최신 collections API를 먼저 시도하고, 실패하면 legacy metric API를 사용합니다.
    """
    try:
        from openai import AsyncOpenAI
        from ragas.llms import llm_factory
        from ragas.metrics.collections import (
            AnswerCorrectness,
            AnswerRelevancy,
            ContextPrecision,
            ContextRecall,
            Faithfulness,
        )

        llm = llm_factory("gpt-4o-mini", client=AsyncOpenAI())
        metric_classes = {
            "faithfulness": Faithfulness,
            "answer_relevancy": AnswerRelevancy,
            "answer_correctness": AnswerCorrectness,
            "context_precision": ContextPrecision,
            "context_recall": ContextRecall,
        }
        return "collections", {
            name: metric_classes[name](llm=llm)
            for name in metric_names
            if name in metric_classes
        }
    except Exception as first_exc:
        try:
            from openai import AsyncOpenAI
            from ragas.llms import llm_factory
            from ragas.metrics import (
                AnswerCorrectness,
                Faithfulness,
                LLMContextPrecisionWithReference,
                LLMContextRecall,
                ResponseRelevancy,
            )

            llm = llm_factory("gpt-4o-mini", client=AsyncOpenAI())
            metric_classes = {
                "faithfulness": Faithfulness,
                "answer_relevancy": ResponseRelevancy,
                "answer_correctness": AnswerCorrectness,
                "context_precision": LLMContextPrecisionWithReference,
                "context_recall": LLMContextRecall,
            }
            return "legacy", {
                name: metric_classes[name](llm=llm)
                for name in metric_names
                if name in metric_classes
            }
        except Exception as exc:
            raise RuntimeError(
                "RAGAS가 설치되어 있지 않거나 지원하지 않는 버전입니다. "
                "또는 RAGAS 의존성인 pandas/datasets 로딩에 실패했습니다. "
                "자동 fallback 평가를 사용하려면 --evaluator auto 또는 "
                "--evaluator openai-lightweight로 실행하세요. "
                f"첫 번째 오류: {first_exc}"
            ) from exc


def metric_value(result: Any) -> float | None:
    if result is None:
        return None
    value = getattr(result, "value", result)
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


async def score_with_collections_api(
    metrics: dict[str, Any],
    *,
    question: str,
    answer: str,
    contexts: list[str],
    reference: str,
) -> dict[str, Any]:
    scores: dict[str, Any] = {}
    for name, metric in metrics.items():
        kwargs = {
            "user_input": question,
            "response": answer,
            "retrieved_contexts": contexts,
            "reference": reference,
        }
        try:
            result = await metric.ascore(**kwargs)
            scores[name] = {
                "score": metric_value(result),
                "reason": getattr(result, "reason", None),
            }
        except Exception as exc:
            scores[name] = {
                "score": None,
                "error": str(exc),
            }
    return scores


async def score_with_legacy_api(
    metrics: dict[str, Any],
    *,
    question: str,
    answer: str,
    contexts: list[str],
    reference: str,
) -> dict[str, Any]:
    try:
        from ragas import SingleTurnSample
    except ImportError:
        from ragas.dataset_schema import SingleTurnSample

    sample = SingleTurnSample(
        user_input=question,
        response=answer,
        retrieved_contexts=contexts,
        reference=reference,
    )

    scores: dict[str, Any] = {}
    for name, metric in metrics.items():
        try:
            result = await metric.single_turn_ascore(sample)
            scores[name] = {
                "score": metric_value(result),
                "reason": getattr(result, "reason", None),
            }
        except Exception as exc:
            scores[name] = {
                "score": None,
                "error": str(exc),
            }
    return scores


def build_lightweight_eval_prompt(
    *,
    question: str,
    answer: str,
    contexts: list[str],
    reference: str,
    metric_names: list[str],
) -> str:
    contexts_text = "\n\n".join(
        f"[Context {index}]\n{context}"
        for index, context in enumerate(contexts, start=1)
    )
    metrics_text = ", ".join(metric_names)
    return f"""
당신은 RAG 평가자입니다. 아래 RAG 결과를 0.0부터 1.0 사이 점수로 평가하세요.

평가 지표:
- faithfulness: 답변의 주장들이 검색 context에 근거하는 정도
- answer_relevancy: 답변이 사용자 질문에 직접 대응하는 정도
- answer_correctness: 답변이 reference 기준 답변과 사실적으로 일치하는 정도
- context_precision: 검색 context 중 질문/답변에 관련 있는 문서가 상위에 잘 배치된 정도
- context_recall: reference 답변에 필요한 핵심 정보가 검색 context에 포함된 정도

반드시 JSON만 출력하세요. 사용할 metric key는 다음만 허용합니다:
{metrics_text}

출력 형식:
{{
  "faithfulness": {{"score": 0.0, "reason": "..."}},
  "answer_relevancy": {{"score": 0.0, "reason": "..."}},
  "answer_correctness": {{"score": 0.0, "reason": "..."}},
  "context_precision": {{"score": 0.0, "reason": "..."}},
  "context_recall": {{"score": 0.0, "reason": "..."}}
}}

[사용자 질문]
{question}

[B파트 답변]
{answer}

[Reference 기준 답변]
{reference}

[검색 Context]
{contexts_text}
""".strip()


def normalize_lightweight_scores(
    payload: Any, metric_names: list[str]
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            name: {
                "score": None,
                "error": "OpenAI judge가 JSON object를 반환하지 않았습니다.",
            }
            for name in metric_names
        }

    scores: dict[str, Any] = {}
    for name in metric_names:
        raw_metric = payload.get(name)
        if isinstance(raw_metric, dict):
            raw_score = raw_metric.get("score")
            reason = raw_metric.get("reason")
        else:
            raw_score = raw_metric
            reason = None

        try:
            score = round(max(0.0, min(1.0, float(raw_score))), 4)
        except (TypeError, ValueError):
            score = None

        scores[name] = {
            "score": score,
            "reason": reason,
        }
    return scores


async def score_with_openai_lightweight(
    *,
    question: str,
    answer: str,
    contexts: list[str],
    reference: str,
    metric_names: list[str],
) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY가 없어 OpenAI fallback 평가를 실행할 수 없습니다."
        )

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    prompt = build_lightweight_eval_prompt(
        question=question,
        answer=answer,
        contexts=contexts,
        reference=reference,
        metric_names=metric_names,
    )
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "당신은 RAG 평가자입니다. 반드시 JSON object만 반환하세요.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    try:
        payload = json.loads(response.choices[0].message.content or "{}")
    except json.JSONDecodeError as exc:
        return {
            name: {
                "score": None,
                "error": f"OpenAI judge JSON 파싱 실패: {exc}",
            }
            for name in metric_names
        }
    return normalize_lightweight_scores(payload, metric_names)


async def run_case(
    question_item: dict[str, Any],
    *,
    top_k: int,
    max_contexts: int,
    metric_api: str,
    metrics: dict[str, Any] | None,
    metric_names: list[str],
) -> dict[str, Any]:
    question = str(question_item["question"])
    reference = str(question_item["reference"])

    try:
        final_state = await graph.ainvoke({"message": question, "top_k": top_k})
    except Exception as exc:
        return {
            "id": question_item.get("id"),
            "group": question_item.get("group"),
            "question": question,
            "reference": reference,
            "error": str(exc),
            "scores": {},
        }

    answer = str(final_state.get("final_answer") or "")
    contexts = get_retrieved_contexts(final_state, max_contexts=max_contexts)
    if metric_api == "openai-lightweight":
        scores = await score_with_openai_lightweight(
            question=question,
            answer=answer,
            contexts=contexts,
            reference=reference,
            metric_names=metric_names,
        )
    elif metric_api == "collections":
        scores = await score_with_collections_api(
            metrics or {},
            question=question,
            answer=answer,
            contexts=contexts,
            reference=reference,
        )
    else:
        scores = await score_with_legacy_api(
            metrics or {},
            question=question,
            answer=answer,
            contexts=contexts,
            reference=reference,
        )

    return {
        "id": question_item.get("id"),
        "group": question_item.get("group"),
        "question": question,
        "reference": reference,
        "expected_context_keywords": question_item.get("expected_context_keywords", []),
        "answer_preview": answer[:1200],
        "retrieved_context_count": len(contexts),
        "retrieved": summarize_retrieved(final_state),
        "scores": scores,
    }


def build_summary(
    items: list[dict[str, Any]], metric_names: list[str]
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total_questions": len(items),
        "error_count": sum(1 for item in items if item.get("error")),
    }

    for metric_name in metric_names:
        values = [
            item.get("scores", {}).get(metric_name, {}).get("score") for item in items
        ]
        numeric_values = [
            float(value) for value in values if isinstance(value, (int, float))
        ]
        summary[f"average_{metric_name}"] = (
            round(mean(numeric_values), 4) if numeric_values else None
        )
    return summary


async def run_evaluation(
    questions: list[dict[str, Any]],
    *,
    top_k: int,
    max_contexts: int,
    metric_names: list[str],
    evaluator: str,
) -> dict[str, Any]:
    metrics: dict[str, Any] | None = None
    ragas_error = None

    if evaluator == "openai-lightweight":
        metric_api = "openai-lightweight"
        enabled_metric_names = metric_names
    else:
        try:
            metric_api, metrics = load_ragas_metric_objects(metric_names)
            enabled_metric_names = list(metrics.keys())
        except Exception as exc:
            if evaluator == "ragas":
                raise
            ragas_error = str(exc)
            print(
                "[알림] RAGAS 로딩 실패. OpenAI lightweight 평가자로 자동 전환합니다."
            )
            print(f"[RAGAS 오류] {ragas_error}")
            metric_api = "openai-lightweight"
            enabled_metric_names = metric_names

    items: list[dict[str, Any]] = []

    for question_item in questions:
        print(
            f"RAGAS 평가 중: {question_item.get('id')} - {question_item.get('question')}"
        )
        items.append(
            await run_case(
                question_item,
                top_k=top_k,
                max_contexts=max_contexts,
                metric_api=metric_api,
                metrics=metrics,
                metric_names=enabled_metric_names,
            )
        )

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "top_k": top_k,
            "max_contexts": max_contexts,
            "metric_api": metric_api,
            "evaluator": evaluator,
            "metrics": enabled_metric_names,
            "ragas_error": ragas_error,
        },
        "summary": build_summary(items, enabled_metric_names),
        "items": items,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="B파트 RAGAS reference 기반 평가")
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-contexts", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--evaluator",
        choices=["auto", "ragas", "openai-lightweight"],
        default="auto",
        help="auto는 RAGAS를 먼저 시도하고 실패하면 OpenAI lightweight 평가자로 전환합니다.",
    )
    parser.add_argument(
        "--metrics",
        nargs="+",
        default=DEFAULT_METRICS,
        choices=DEFAULT_METRICS,
    )
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

    report = asyncio.run(
        run_evaluation(
            questions=questions,
            top_k=args.top_k,
            max_contexts=args.max_contexts,
            metric_names=args.metrics,
            evaluator=args.evaluator,
        )
    )
    write_json(args.output, report)
    print("\n[요약]")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"\n결과 저장: {args.output}")


if __name__ == "__main__":
    main()
