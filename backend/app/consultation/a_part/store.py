"""A파트 상담 상태를 서버 메모리에 저장하는 저장소."""

from __future__ import annotations

from threading import RLock

from backend.app.consultation.a_part.models import ConversationState


class ConversationStoreError(RuntimeError):
    """대화 상태 저장소의 공통 오류."""


class ConversationNotFoundError(ConversationStoreError):
    """요청한 conversation_id가 메모리에 없을 때 발생한다."""

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        super().__init__(
            "상담 상태를 찾을 수 없습니다. "
            "서버가 재시작됐거나 이미 초기화된 상담일 수 있습니다: "
            f"{conversation_id}"
        )


class ConversationAlreadyExistsError(ConversationStoreError):
    """같은 conversation_id를 중복 생성할 때 발생한다."""


class MemoryConversationStore:
    """한 프로세스 안에서만 유지되는 thread-safe 메모리 저장소.

    MVP 단계의 임시 저장소이므로 서버 프로세스가 재시작되면 모든 상태가 사라진다.
    외부에서 받은 객체를 그대로 보관하지 않고 깊은 복사본을 저장해 우발적인 변경을 막는다.
    """

    def __init__(self) -> None:
        self._states: dict[str, ConversationState] = {}
        self._lock = RLock()

    def create(self, state: ConversationState) -> ConversationState:
        with self._lock:
            if state.conversation_id in self._states:
                raise ConversationAlreadyExistsError(
                    f"이미 존재하는 conversation_id입니다: {state.conversation_id}"
                )
            stored = state.model_copy(deep=True)
            stored.touch()
            self._states[stored.conversation_id] = stored
            return stored.model_copy(deep=True)

    def get(self, conversation_id: str) -> ConversationState:
        normalized = conversation_id.strip()
        if not normalized:
            raise ValueError("conversation_id는 빈 문자열일 수 없습니다.")

        with self._lock:
            try:
                state = self._states[normalized]
            except KeyError as exc:
                raise ConversationNotFoundError(normalized) from exc
            return state.model_copy(deep=True)

    def save(self, state: ConversationState) -> ConversationState:
        with self._lock:
            if state.conversation_id not in self._states:
                raise ConversationNotFoundError(state.conversation_id)
            stored = state.model_copy(deep=True)
            stored.touch()
            self._states[stored.conversation_id] = stored
            return stored.model_copy(deep=True)

    def upsert(self, state: ConversationState) -> ConversationState:
        with self._lock:
            stored = state.model_copy(deep=True)
            stored.touch()
            self._states[stored.conversation_id] = stored
            return stored.model_copy(deep=True)

    def delete(self, conversation_id: str) -> bool:
        normalized = conversation_id.strip()
        if not normalized:
            raise ValueError("conversation_id는 빈 문자열일 수 없습니다.")

        with self._lock:
            return self._states.pop(normalized, None) is not None

    def reset(self, conversation_id: str) -> ConversationState:
        """상담을 삭제하고 삭제 직전 상태를 반환한다."""

        with self._lock:
            try:
                state = self._states.pop(conversation_id)
            except KeyError as exc:
                raise ConversationNotFoundError(conversation_id) from exc
            return state.model_copy(deep=True)

    def clear(self) -> int:
        with self._lock:
            count = len(self._states)
            self._states.clear()
            return count

    def exists(self, conversation_id: str) -> bool:
        with self._lock:
            return conversation_id in self._states

    def count(self) -> int:
        with self._lock:
            return len(self._states)

    def list_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._states)


DEFAULT_CONVERSATION_STORE = MemoryConversationStore()
