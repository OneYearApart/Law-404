"""
B파트 DB 기반 멀티턴 대화 기억 테스트 스크립트.

전제:
- docker compose로 PostgreSQL이 떠 있어야 합니다.
- alembic upgrade head로 conversations/messages 테이블이 있어야 합니다.
- 테스트에 사용할 users.id가 DB에 존재해야 합니다.

실행 예:
    cd C:\\education\\ai-project\\Law-404
    C:\\Users\\user\\anaconda3\\envs\\eduvenv\\python.exe backend\\data\\b_part\\evaluation\\run_db_memory_test.py --user-id 1
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.auth.orm  # noqa: E402,F401  # users 테이블 FK 해석을 위해 SQLAlchemy metadata에 등록합니다.
from app.conversations.errors import ConversationNotFoundError  # noqa: E402
from app.conversations.repository import (  # noqa: E402
    create_conversation,
    get_session_state,
    list_conversations,
    load_conversation,
    save_message,
    update_session_state,
)
from app.core.config import settings  # noqa: E402

if not hasattr(settings, "openai_api_key") and hasattr(settings, "OPENAI_API_KEY"):
    object.__setattr__(settings, "openai_api_key", settings.OPENAI_API_KEY)

from app.graph.parts.b_part.graph import graph as b_graph  # noqa: E402
from app.graph.parts.b_part.memory import (  # noqa: E402
    build_persistable_session_state,
    seed_memory_from_persisted_data,
)

QUESTION_1 = "계약이 곧 끝나는데 집주인이 아무 말도 없습니다. 자동으로 연장되나요?"
QUESTION_2 = "2026년 10월 10일입니다."


async def run_graph_with_persisted_memory(
    *,
    user_id: int,
    conversation_id: int,
    message: str,
) -> dict[str, Any]:
    """DB messages/state를 graph InMemory store에 주입한 뒤 1턴을 실행하고 저장합니다."""
    persisted_state = await get_session_state(conversation_id, user_id)
    persisted_messages = await load_conversation(conversation_id, user_id)
    session_id = str(conversation_id)

    seed_memory_from_persisted_data(
        session_id,
        messages=persisted_messages,
        state=persisted_state,
    )

    await save_message(user_id, "b", "user", message, conversation_id)
    final_state = await b_graph.ainvoke(
        {
            "message": message,
            "conversation_id": conversation_id,
            "top_k": 5,
        }
    )
    await save_message(
        user_id,
        "b",
        "assistant",
        final_state.get("final_answer", ""),
        conversation_id,
    )
    await update_session_state(
        conversation_id,
        user_id,
        build_persistable_session_state(session_id, final_state),
    )
    return final_state


def summarize_turn(final_state: dict[str, Any]) -> dict[str, Any]:
    """발표/디버깅용 핵심 결과만 추립니다."""
    memory = final_state.get("memory") or {}
    state = memory.get("state") or {}
    return {
        "categories": final_state.get("categories", []),
        "missing_questions": final_state.get("missing_questions", []),
        "rule_count": len(final_state.get("rule_results", [])),
        "retrieved_count": len(final_state.get("retrieved", [])),
        "used_memory": memory.get("used_memory"),
        "memory_reason": memory.get("reason"),
        "contextual_question": memory.get("contextual_question"),
        "memory_state": state,
        "answer_preview": str(final_state.get("final_answer", ""))[:300],
    }


async def assert_user_exists(user_id: int) -> None:
    """repository 소유권 검증을 이용해 user 존재 여부를 간접 확인합니다."""
    conversations = await list_conversations(user_id)
    if isinstance(conversations, list):
        return


async def run_test(user_id: int) -> dict[str, Any]:
    await assert_user_exists(user_id)
    conversation = await create_conversation(user_id, "b")
    conversation_id = conversation.id

    turn_1 = await run_graph_with_persisted_memory(
        user_id=user_id,
        conversation_id=conversation_id,
        message=QUESTION_1,
    )
    state_after_turn_1 = await get_session_state(conversation_id, user_id)
    messages_after_turn_1 = await load_conversation(conversation_id, user_id)

    turn_2 = await run_graph_with_persisted_memory(
        user_id=user_id,
        conversation_id=conversation_id,
        message=QUESTION_2,
    )
    state_after_turn_2 = await get_session_state(conversation_id, user_id)
    messages_after_turn_2 = await load_conversation(conversation_id, user_id)

    turn_2_memory = turn_2.get("memory") or {}
    passed = (
        len(messages_after_turn_1) >= 2
        and len(messages_after_turn_2) >= 4
        and bool(state_after_turn_1)
        and bool(state_after_turn_2)
        and turn_2_memory.get("used_memory") is True
        and "2026" in str(turn_2_memory.get("contextual_question", ""))
    )

    return {
        "passed": passed,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "turn_1": summarize_turn(turn_1),
        "turn_2": summarize_turn(turn_2),
        "message_count_after_turn_1": len(messages_after_turn_1),
        "message_count_after_turn_2": len(messages_after_turn_2),
        "state_after_turn_1": state_after_turn_1,
        "state_after_turn_2": state_after_turn_2,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="B파트 DB 기반 멀티턴 대화 기억 테스트"
    )
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument(
        "--output",
        default="backend/tests/b_part/db_memory_test_results.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = asyncio.run(run_test(args.user_id))
    except ConversationNotFoundError as error:
        print(
            "[실패] 해당 user_id로 대화방을 만들거나 조회할 수 없습니다. "
            "로그인 테스트 계정의 users.id를 --user-id로 지정하세요."
        )
        print(error)
        raise SystemExit(1) from error

    output_path = ROOT_DIR / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n결과 저장: {output_path}")


if __name__ == "__main__":
    main()
