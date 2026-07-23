"""
B파트 RAG MVP 답변 생성 테스트 스크립트.

FastAPI 서버를 띄우지 않고 graph.ainvoke()를 직접 호출해서
B파트 내부 RAG 흐름이 끝까지 동작하는지 확인합니다.

확인 흐름:
    사용자 질문
    -> graph.ainvoke()
    -> Intent Analyzer
    -> Retriever 검색
    -> GPT 답변 생성
    -> final_answer 출력

실행 위치:
    C:\\education\\ai-project\\Law-404

기본 실행:
    C:\\Users\\user\\anaconda3\\envs\\eduvenv\\python.exe backend\\data\\b_part\\evaluation\\run_graph_answer_test.py

질문 변경:
    C:\\Users\\user\\anaconda3\\envs\\eduvenv\\python.exe backend\\data\\b_part\\evaluation\\run_graph_answer_test.py --question "월세를 50만 원에서 60만 원으로 올려달라고 합니다."

검색 개수 변경:
    C:\\Users\\user\\anaconda3\\envs\\eduvenv\\python.exe backend\\data\\b_part\\evaluation\\run_graph_answer_test.py --top-k 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[3]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.graph.parts.b_part.graph import graph  # noqa: E402

DEFAULT_QUESTION = (
    "집주인이 수리를 계속 안 해줘서 계약을 중도해지하고 싶습니다. 가능한가요?"
)


def simplify_retrieved_documents(
    retrieved: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    검색 결과 전체를 그대로 출력하면 너무 길기 때문에,
    테스트에서 확인하기 좋은 핵심 필드만 남깁니다.
    """
    simplified = []

    for rank, document in enumerate(retrieved, start=1):
        simplified.append(
            {
                "rank": rank,
                "id": document.get("id"),
                "source_type": document.get("source_type"),
                "category": document.get("category"),
                "title": document.get("title"),
                "chunk_type": document.get("chunk_type"),
                "similarity": document.get("similarity"),
                "content_preview": str(document.get("content", ""))[:250],
            }
        )

    return simplified


async def run_test(question: str, top_k: int) -> None:
    """
    graph.ainvoke()를 직접 호출해 B파트 RAG 답변 생성 흐름을 테스트합니다.
    """
    request = {
        "message": question,
        "top_k": top_k,
    }

    final_state = await graph.ainvoke(request)

    print("\n" + "=" * 80)
    print("[사용자 질문]")
    print(final_state.get("question", ""))

    print("\n" + "=" * 80)
    print("[예측 카테고리]")
    print(json.dumps(final_state.get("categories", []), ensure_ascii=False, indent=2))

    print("\n" + "=" * 80)
    print("[추가 확인 질문]")
    print(
        json.dumps(
            final_state.get("missing_questions", []), ensure_ascii=False, indent=2
        )
    )

    print("\n" + "=" * 80)
    print("[검색된 문서 요약]")
    retrieved = final_state.get("retrieved", [])
    print(
        json.dumps(
            simplify_retrieved_documents(retrieved),
            ensure_ascii=False,
            indent=2,
        )
    )

    print("\n" + "=" * 80)
    print("[최종 답변]")
    print(final_state.get("final_answer", ""))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="B파트 graph.ainvoke 답변 생성 테스트")
    parser.add_argument("--question", default=DEFAULT_QUESTION)
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_test(question=args.question, top_k=args.top_k))


if __name__ == "__main__":
    main()
