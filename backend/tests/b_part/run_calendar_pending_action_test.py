"""
B파트 캘린더 pending_action 2턴 대화 테스트 스크립트.

이 스크립트는 실제 Calendar MCP를 호출하지 않습니다.
1턴에서 계약 종료일 기반 캘린더 후보 일정을 만들고,
2턴에서 사용자의 승인 답변과 pending_action을 함께 넘겨
등록 준비 상태로 전환되는지 확인합니다.

실행 위치:
    C:\\education\\ai-project\\Law-404

실행 예시:
    C:\\Users\\user\\anaconda3\\envs\\eduvenv\\python.exe backend\\data\\b_part\\evaluation\\run_calendar_pending_action_test.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[2]

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.graph.parts.b_part.graph import graph  # noqa: E402


DEFAULT_FIRST_QUESTION = "계약 종료일이 2027년 3월 1일인데 갱신요구권 일정도 캘린더에 등록할 수 있나요?"
DEFAULT_APPROVAL_MESSAGE = "응 등록해줘"


def print_json_section(title: str, data: Any) -> None:
    print("\n" + "=" * 80)
    print(f"[{title}]")
    print(json.dumps(data, ensure_ascii=False, indent=2))


async def run_test(first_question: str, approval_message: str, top_k: int) -> None:
    first_request = {
        "message": first_question,
        "top_k": top_k,
    }
    first_state = await graph.ainvoke(first_request)

    print("\n" + "=" * 80)
    print("[1턴 사용자 질문]")
    print(first_question)

    print_json_section("1턴 Rule Engine 계산 결과", first_state.get("rule_results", []))
    print_json_section("1턴 Calendar Event Candidates", first_state.get("calendar_events", []))
    print_json_section("1턴 Pending Action", first_state.get("pending_action"))

    pending_action = first_state.get("pending_action")
    if not pending_action:
        print("\n" + "=" * 80)
        print("[테스트 중단]")
        print("1턴에서 pending_action이 생성되지 않았습니다. 계약 종료일이 인식되는 질문인지 확인하세요.")
        return

    second_request = {
        "message": approval_message,
        "pending_action": pending_action,
        "top_k": top_k,
    }
    second_state = await graph.ainvoke(second_request)

    print("\n" + "=" * 80)
    print("[2턴 사용자 답변]")
    print(approval_message)

    print_json_section("2턴 Calendar Registration", second_state.get("calendar_registration"))
    print_json_section("2턴 Pending Action", second_state.get("pending_action"))

    print("\n" + "=" * 80)
    print("[2턴 최종 답변]")
    print(second_state.get("final_answer", ""))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="B파트 캘린더 pending_action 2턴 테스트")
    parser.add_argument("--question", default=DEFAULT_FIRST_QUESTION)
    parser.add_argument("--approval", default=DEFAULT_APPROVAL_MESSAGE)
    parser.add_argument("--top-k", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(
        run_test(
            first_question=args.question,
            approval_message=args.approval,
            top_k=args.top_k,
        )
    )


if __name__ == "__main__":
    main()
