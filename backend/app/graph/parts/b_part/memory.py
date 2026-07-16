"""
B파트 InMemory 대화 기억 모듈.

PostgresChatMessageHistory로 전환하기 전 MVP 단계에서 session/conversation 단위
멀티턴 대화를 테스트하기 위한 임시 저장소입니다. 서버가 재시작되면 기록은 사라집니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.graph.parts.b_part.rules import has_date_in_text, parse_year_month_from_text


MAX_HISTORY_MESSAGES = 8


@dataclass
class BPartChatMessage:
    """B파트 대화 메시지 한 건."""

    role: str
    content: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
        }


class BPartInMemoryChatMessageHistory:
    """session_id별 메시지를 메모리에 보관하는 간단한 저장소입니다."""

    def __init__(self) -> None:
        self._store: dict[str, list[BPartChatMessage]] = {}
        self._state: dict[str, dict[str, Any]] = {}

    def add_message(self, session_id: str, role: str, content: str) -> None:
        if not session_id or not content.strip():
            return

        messages = self._store.setdefault(session_id, [])
        messages.append(
            BPartChatMessage(
                role=role,
                content=content.strip(),
                created_at=datetime.now().isoformat(timespec="seconds"),
            )
        )

        if len(messages) > MAX_HISTORY_MESSAGES:
            self._store[session_id] = messages[-MAX_HISTORY_MESSAGES:]

    def get_messages(self, session_id: str) -> list[BPartChatMessage]:
        return list(self._store.get(session_id, []))

    def get_state(self, session_id: str) -> dict[str, Any]:
        return dict(self._state.get(session_id, {}))

    def replace_messages(self, session_id: str, messages: list[BPartChatMessage]) -> None:
        """외부 저장소에서 읽은 메시지 목록으로 현재 세션 메시지를 교체합니다."""
        if not session_id:
            return
        self._store[session_id] = list(messages[-MAX_HISTORY_MESSAGES:])

    def replace_state(self, session_id: str, state: dict[str, Any] | None) -> None:
        """외부 저장소에서 읽은 state로 현재 세션 상태를 교체합니다."""
        if not session_id:
            return
        self._state[session_id] = dict(state or {})

    def update_state(self, session_id: str, updates: dict[str, Any]) -> None:
        if not session_id:
            return
        state = self._state.setdefault(session_id, {})
        state.update(updates)

    def clear_state_fields(self, session_id: str, fields: list[str]) -> None:
        state = self._state.get(session_id)
        if not state:
            return
        for field in fields:
            state.pop(field, None)

    def clear(self, session_id: str) -> None:
        self._store.pop(session_id, None)
        self._state.pop(session_id, None)


memory_store = BPartInMemoryChatMessageHistory()


def seed_memory_from_persisted_data(
    session_id: str,
    *,
    messages: list[Any] | None = None,
    state: dict[str, Any] | None = None,
) -> None:
    """DB에 저장된 messages/state를 B파트 InMemory store에 주입합니다."""
    if not session_id:
        return

    restored_messages: list[BPartChatMessage] = []
    for message in messages or []:
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        created_at = getattr(message, "created_at", None)
        if not isinstance(role, str) or not isinstance(content, str):
            continue
        restored_messages.append(
            BPartChatMessage(
                role=role,
                content=content,
                created_at=(
                    created_at.isoformat(timespec="seconds")
                    if hasattr(created_at, "isoformat")
                    else str(created_at or "")
                ),
            )
        )

    memory_state = {}
    if isinstance(state, dict):
        raw_memory_state = state.get("memory_state", state)
        if isinstance(raw_memory_state, dict):
            memory_state = raw_memory_state

    memory_store.replace_messages(session_id, restored_messages)
    memory_store.replace_state(session_id, memory_state)


def build_persistable_session_state(
    session_id: str,
    final_state: dict[str, Any],
) -> dict[str, Any]:
    """B파트 graph 실행 결과 중 턴 간 유지할 값만 conversations.state에 저장합니다."""
    memory = final_state.get("memory")
    if not isinstance(memory, dict):
        memory = {}

    return {
        "memory_state": memory_store.get_state(session_id),
        "pending_action": final_state.get("pending_action"),
        "calendar_events": final_state.get("calendar_events", []),
        "last_categories": final_state.get("categories", []),
        "last_missing_questions": final_state.get("missing_questions", []),
        "last_contextual_question": memory.get("contextual_question"),
        "last_original_question": memory.get("original_question"),
        "last_used_memory": memory.get("used_memory"),
    }


def extract_conversation_id(request: dict[str, Any]) -> str | None:
    """요청에서 conversation/session 식별자를 꺼냅니다."""
    for key in ("conversation_id", "session_id", "thread_id", "chat_id"):
        value = request.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def is_short_followup_answer(message: str) -> bool:
    """
    이전 질문에 대한 짧은 후속 답변인지 규칙 기반으로 판단합니다.

    예:
    - 2026년 10월 10일입니다.
    - 50만 원에서 60만 원이요.
    - 문자로 받았어요.
    """
    text = message.strip()
    if not text:
        return False

    has_date = has_date_in_text(text)
    has_year_month = parse_year_month_from_text(text) is not None
    has_money = bool(re.search(r"\d+\s*(만\s*)?원|\d+\s*만원", text))
    has_duration = has_duration_in_text(text)
    has_followup_cue = has_followup_cue_in_text(text)
    has_evidence_answer = any(
        keyword in text
        for keyword in [
            "문자",
            "카톡",
            "사진",
            "녹음",
            "증거",
            "받았",
            "보냈",
            "없어요",
            "있어요",
        ]
    )
    is_short = len(text) <= 40

    return is_short and (
        has_date
        or has_year_month
        or has_money
        or has_duration
        or has_followup_cue
        or has_evidence_answer
    )


def has_duration_in_text(text: str) -> bool:
    """1주일, 3일, 두 달처럼 기간을 나타내는 답변인지 확인합니다."""
    duration_pattern = r"\d+\s*(일|주|주일|개월|달|년)"
    if re.search(duration_pattern, text):
        return True

    return any(
        keyword in text
        for keyword in [
            "일주일",
            "한 주",
            "한달",
            "한 달",
            "며칠",
            "몇일",
            "몇 주",
            "몇 달",
            "지났",
            "지난",
        ]
    )


def has_followup_cue_in_text(text: str) -> bool:
    """이전 말에 대한 정정/반복/불만 표현인지 확인합니다."""
    return any(
        keyword in text
        for keyword in [
            "방금",
            "아까",
            "말했",
            "말했잖",
            "말했듯",
            "그거",
            "그건",
            "그게",
            "위에서",
            "앞에서",
        ]
    )


def has_assistant_asked_missing_info(messages: list[BPartChatMessage]) -> bool:
    """최근 assistant 메시지가 추가 정보를 요청했는지 확인합니다."""
    for message in reversed(messages):
        if message.role != "assistant":
            continue
        content = message.content
        return any(
            keyword in content
            for keyword in [
                "알려주세요",
                "언제인지",
                "언제였는지",
                "얼마인지",
                "추가 확인",
                "확인 질문",
            ]
        )
    return False


def build_history_text(messages: list[BPartChatMessage]) -> str:
    """최근 대화를 LLM/RAG 입력에 넣기 좋은 텍스트로 변환합니다."""
    lines: list[str] = []
    for message in messages[-MAX_HISTORY_MESSAGES:]:
        role_label = "사용자" if message.role == "user" else "챗봇"
        lines.append(f"{role_label}: {message.content}")
    return "\n".join(lines)


def get_last_user_message(messages: list[BPartChatMessage]) -> str:
    """최근 사용자 질문을 가져옵니다."""
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return ""


def get_recent_user_messages(messages: list[BPartChatMessage], limit: int = 3) -> str:
    """최근 사용자 메시지 여러 개를 시간순으로 가져옵니다."""
    user_messages = [
        message.content
        for message in messages
        if message.role == "user"
    ]
    recent_messages = user_messages[-limit:]
    return "\n".join(f"- {message}" for message in recent_messages)


def get_last_missing_info_request(messages: list[BPartChatMessage]) -> str:
    """최근 챗봇 답변에서 추가 확인 질문에 가까운 문장만 가져옵니다."""
    for message in reversed(messages):
        if message.role != "assistant":
            continue

        lines = [
            line.strip("-• \t")
            for line in message.content.splitlines()
            if line.strip()
        ]
        request_lines = [
            line
            for line in lines
            if (
                any(
                    keyword in line
                    for keyword in [
                        "알려주세요",
                        "언제인가요",
                        "언제인지",
                        "언제였는지",
                        "얼마인가요",
                        "얼마인지",
                    ]
                )
                and "추가 확인 질문" not in line
            )
        ]
        if request_lines:
            return "\n".join(request_lines[-3:])

    return "챗봇이 추가 정보를 요청했습니다."


def build_contextual_question(
    current_question: str,
    history_messages: list[BPartChatMessage],
) -> tuple[str, dict[str, Any]]:
    """
    현재 입력이 후속 답변이면 이전 대화와 결합한 contextual_question을 만듭니다.
    """
    if not history_messages:
        return current_question, {
            "used_memory": False,
            "reason": "history_empty",
            "history_message_count": 0,
        }

    should_use_memory = (
        is_short_followup_answer(current_question)
        and has_assistant_asked_missing_info(history_messages)
    )

    if not should_use_memory:
        return current_question, {
            "used_memory": False,
            "reason": "not_followup_answer",
            "history_message_count": len(history_messages),
        }

    previous_user_question = get_recent_user_messages(history_messages)
    if not previous_user_question:
        previous_user_question = get_last_user_message(history_messages)
    missing_info_request = get_last_missing_info_request(history_messages)
    contextual_question = (
        "최근 사용자 질문/답변:\n"
        f"{previous_user_question}\n\n"
        "챗봇이 요청한 추가 정보:\n"
        f"{missing_info_request}\n\n"
        "현재 사용자 답변:\n"
        f"{current_question}\n\n"
        "위 정보를 함께 고려해서 사용자의 원래 주택임대차 계약 중 분쟁 질문에 답변하세요."
    )

    return contextual_question, {
        "used_memory": True,
        "reason": "short_followup_after_missing_info",
        "history_message_count": len(history_messages),
    }
