"""
B파트 InMemory 멀티턴 대화 테스트 스크립트.

FastAPI 서버 없이 graph.ainvoke()를 직접 호출해 같은 conversation_id에서
이전 질문과 후속 답변이 결합되는지 확인합니다.

실행 위치:
    C:\\education\\ai-project\\Law-404

실행:
    C:\\Users\\user\\anaconda3\\envs\\eduvenv\\python.exe backend\\data\\b_part\\evaluation\\run_graph_memory_test.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[2]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.graph.parts.b_part.graph import graph  # noqa: E402
from app.graph.parts.b_part.memory import memory_store  # noqa: E402

CONVERSATION_ID = "b-part-memory-demo"
FIRST_TURN = "계약이 곧 끝나는데 집주인이 아무 말도 없습니다. 자동으로 연장되나요?"
SECOND_TURN = "26년 10월 10일"

REPAIR_CONVERSATION_ID = "b-part-memory-repair-demo"
REPAIR_TURNS = [
    "보일러를 수리 안 해줘",
    "수리 요청 후 1주일이 지났어",
    "방금 말했잖아 1주일 지났다고",
]

PARTIAL_DATE_CONVERSATION_ID = "b-part-memory-partial-date-demo"
PARTIAL_DATE_TURNS = [
    "계약이 곧 끝나는데 집주인이 아무 말도 없습니다. 자동으로 연장되나요?",
    "26년 9월입니다.",
    "계약 종료일은 언제인가요?",
    "10일입니다.",
]


def summarize_state(final_state: dict[str, Any]) -> dict[str, Any]:
    """멀티턴 테스트에서 확인할 핵심 필드만 요약합니다."""
    return {
        "question": final_state.get("question"),
        "categories": final_state.get("categories", []),
        "context_result": final_state.get("context_result"),
        "memory": final_state.get("memory"),
        "missing_questions": final_state.get("missing_questions", []),
        "rule_results": final_state.get("rule_results", []),
        "calendar_events": final_state.get("calendar_events", []),
        "pending_action": final_state.get("pending_action"),
        "final_answer_preview": str(final_state.get("final_answer", ""))[:700],
    }


async def main() -> None:
    memory_store.clear(CONVERSATION_ID)
    memory_store.clear(REPAIR_CONVERSATION_ID)
    memory_store.clear(PARTIAL_DATE_CONVERSATION_ID)

    first_state = await graph.ainvoke(
        {
            "message": FIRST_TURN,
            "conversation_id": CONVERSATION_ID,
            "top_k": 5,
        }
    )

    second_state = await graph.ainvoke(
        {
            "message": SECOND_TURN,
            "conversation_id": CONVERSATION_ID,
            "top_k": 5,
        }
    )

    print("\n" + "=" * 80)
    print("[1턴 입력]")
    print(FIRST_TURN)
    print("\n[1턴 결과 요약]")
    print(json.dumps(summarize_state(first_state), ensure_ascii=False, indent=2))

    print("\n" + "=" * 80)
    print("[2턴 입력]")
    print(SECOND_TURN)
    print("\n[2턴 결과 요약]")
    print(json.dumps(summarize_state(second_state), ensure_ascii=False, indent=2))

    print("\n" + "=" * 80)
    print("[저장된 InMemory 메시지]")
    print(
        json.dumps(
            [
                message.to_dict()
                for message in memory_store.get_messages(CONVERSATION_ID)
            ],
            ensure_ascii=False,
            indent=2,
        )
    )

    repair_states: list[dict[str, Any]] = []
    for turn in REPAIR_TURNS:
        repair_states.append(
            await graph.ainvoke(
                {
                    "message": turn,
                    "conversation_id": REPAIR_CONVERSATION_ID,
                    "top_k": 5,
                }
            )
        )

    print("\n" + "=" * 80)
    print("[수선의무 3턴 테스트]")
    for index, (turn, state) in enumerate(zip(REPAIR_TURNS, repair_states), start=1):
        print(f"\n[{index}턴 입력]")
        print(turn)
        print(f"\n[{index}턴 결과 요약]")
        print(json.dumps(summarize_state(state), ensure_ascii=False, indent=2))

    print("\n" + "=" * 80)
    print("[수선의무 InMemory 메시지]")
    print(
        json.dumps(
            [
                message.to_dict()
                for message in memory_store.get_messages(REPAIR_CONVERSATION_ID)
            ],
            ensure_ascii=False,
            indent=2,
        )
    )

    partial_date_states: list[dict[str, Any]] = []
    for turn in PARTIAL_DATE_TURNS:
        partial_date_states.append(
            await graph.ainvoke(
                {
                    "message": turn,
                    "conversation_id": PARTIAL_DATE_CONVERSATION_ID,
                    "top_k": 5,
                }
            )
        )

    print("\n" + "=" * 80)
    print("[부분 날짜 슬롯 필링 4턴 테스트]")
    for index, (turn, state) in enumerate(
        zip(PARTIAL_DATE_TURNS, partial_date_states), start=1
    ):
        print(f"\n[{index}턴 입력]")
        print(turn)
        print(f"\n[{index}턴 결과 요약]")
        print(json.dumps(summarize_state(state), ensure_ascii=False, indent=2))

    print("\n" + "=" * 80)
    print("[부분 날짜 InMemory 메시지]")
    print(
        json.dumps(
            [
                message.to_dict()
                for message in memory_store.get_messages(PARTIAL_DATE_CONVERSATION_ID)
            ],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
