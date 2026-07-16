"""A파트 상담 상태를 서버 메모리에 저장하는 저장소."""

from __future__ import annotations

from threading import RLock

from app.consultation.a_part.models import ConversationState


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


class PostgresConversationStore:
    """레거시 A파트 전용 상태 테이블 저장소다. 기본 서비스에서는 사용하지 않는다."""

    def __init__(self, database_url: str) -> None:
        normalized = str(database_url or "").strip()
        if not normalized:
            raise ValueError("database_url은 빈 문자열일 수 없습니다.")
        self.database_url = normalized
        self._schema_checked = False
        self._schema_lock = RLock()

    @staticmethod
    def _psycopg2():
        try:
            import psycopg2
            from psycopg2.extras import Json
        except ImportError as error:
            raise ConversationStoreError(
                "PostgreSQL 상담 상태 저장에는 psycopg2-binary가 필요합니다."
            ) from error
        return psycopg2, Json

    def _connect(self):
        psycopg2, _ = self._psycopg2()
        return psycopg2.connect(self.database_url)

    def _ensure_schema(self) -> None:
        if self._schema_checked:
            return
        with self._schema_lock:
            if self._schema_checked:
                return
            try:
                with self._connect() as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            CREATE TABLE IF NOT EXISTS a_part_conversation_states (
                                conversation_id TEXT PRIMARY KEY,
                                state JSONB NOT NULL,
                                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                            )
                            """
                        )
                self._schema_checked = True
            except Exception as error:
                raise ConversationStoreError(
                    "A파트 상담 상태 테이블을 준비하지 못했습니다."
                ) from error

    @staticmethod
    def _normalize_id(conversation_id: str) -> str:
        normalized = str(conversation_id or "").strip()
        if not normalized:
            raise ValueError("conversation_id는 빈 문자열일 수 없습니다.")
        return normalized

    def create(self, state: ConversationState) -> ConversationState:
        self._ensure_schema()
        stored = state.model_copy(deep=True)
        stored.touch()
        _, Json = self._psycopg2()
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO a_part_conversation_states (
                            conversation_id, state, updated_at
                        ) VALUES (%s, %s, NOW())
                        """,
                        (
                            stored.conversation_id,
                            Json(stored.model_dump(mode="json")),
                        ),
                    )
        except Exception as error:
            if getattr(error, "pgcode", None) == "23505":
                raise ConversationAlreadyExistsError(
                    f"이미 존재하는 conversation_id입니다: {stored.conversation_id}"
                ) from error
            raise ConversationStoreError("상담 상태를 생성하지 못했습니다.") from error
        return stored.model_copy(deep=True)

    def get(self, conversation_id: str) -> ConversationState:
        self._ensure_schema()
        normalized = self._normalize_id(conversation_id)
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT state FROM a_part_conversation_states WHERE conversation_id = %s",
                        (normalized,),
                    )
                    row = cursor.fetchone()
        except Exception as error:
            raise ConversationStoreError("상담 상태를 조회하지 못했습니다.") from error
        if row is None:
            raise ConversationNotFoundError(normalized)
        return ConversationState.model_validate(row[0]).model_copy(deep=True)

    def save(self, state: ConversationState) -> ConversationState:
        self._ensure_schema()
        stored = state.model_copy(deep=True)
        stored.touch()
        _, Json = self._psycopg2()
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE a_part_conversation_states
                        SET state = %s, updated_at = NOW()
                        WHERE conversation_id = %s
                        """,
                        (
                            Json(stored.model_dump(mode="json")),
                            stored.conversation_id,
                        ),
                    )
                    updated = cursor.rowcount
        except Exception as error:
            raise ConversationStoreError("상담 상태를 저장하지 못했습니다.") from error
        if not updated:
            raise ConversationNotFoundError(stored.conversation_id)
        return stored.model_copy(deep=True)

    def upsert(self, state: ConversationState) -> ConversationState:
        self._ensure_schema()
        stored = state.model_copy(deep=True)
        stored.touch()
        _, Json = self._psycopg2()
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO a_part_conversation_states (
                            conversation_id, state, updated_at
                        ) VALUES (%s, %s, NOW())
                        ON CONFLICT (conversation_id) DO UPDATE SET
                            state = EXCLUDED.state,
                            updated_at = NOW()
                        """,
                        (
                            stored.conversation_id,
                            Json(stored.model_dump(mode="json")),
                        ),
                    )
        except Exception as error:
            raise ConversationStoreError("상담 상태를 저장하지 못했습니다.") from error
        return stored.model_copy(deep=True)

    def delete(self, conversation_id: str) -> bool:
        self._ensure_schema()
        normalized = self._normalize_id(conversation_id)
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM a_part_conversation_states WHERE conversation_id = %s",
                        (normalized,),
                    )
                    return bool(cursor.rowcount)
        except Exception as error:
            raise ConversationStoreError("상담 상태를 삭제하지 못했습니다.") from error

    def reset(self, conversation_id: str) -> ConversationState:
        state = self.get(conversation_id)
        if not self.delete(conversation_id):
            raise ConversationNotFoundError(conversation_id)
        return state

    def clear(self) -> int:
        self._ensure_schema()
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM a_part_conversation_states")
                    return int(cursor.rowcount)
        except Exception as error:
            raise ConversationStoreError("상담 상태를 초기화하지 못했습니다.") from error

    def exists(self, conversation_id: str) -> bool:
        self._ensure_schema()
        normalized = self._normalize_id(conversation_id)
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM a_part_conversation_states WHERE conversation_id = %s",
                        (normalized,),
                    )
                    return cursor.fetchone() is not None
        except Exception as error:
            raise ConversationStoreError("상담 상태 존재 여부를 확인하지 못했습니다.") from error

    def count(self) -> int:
        self._ensure_schema()
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM a_part_conversation_states")
                    return int(cursor.fetchone()[0])
        except Exception as error:
            raise ConversationStoreError("상담 상태 수를 확인하지 못했습니다.") from error

    def list_ids(self) -> tuple[str, ...]:
        self._ensure_schema()
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT conversation_id FROM a_part_conversation_states ORDER BY updated_at DESC"
                    )
                    return tuple(str(row[0]) for row in cursor.fetchall())
        except Exception as error:
            raise ConversationStoreError("상담 상태 목록을 조회하지 못했습니다.") from error


class SharedConversationStore:
    """팀 공통 conversations/messages 테이블에 A파트 상태를 저장한다.

    A파트의 세부 상태는 conversations.state JSONB에 저장하고,
    실제 사용자·assistant 메시지는 공통 messages 테이블에 저장한다.
    conversation_id는 공통 conversations.id를 문자열로 노출한다.
    """

    def __init__(self, *, part: str = "a") -> None:
        self.part = part

    @staticmethod
    def _normalize_id(conversation_id: str) -> int:
        normalized = str(conversation_id or "").strip()
        if not normalized:
            raise ValueError("conversation_id는 빈 문자열일 수 없습니다.")
        if not normalized.isdigit():
            raise ConversationNotFoundError(normalized)
        return int(normalized)

    @staticmethod
    def _load_models():
        from app.conversations.orm import Conversation, Message
        from app.core.db import SessionLocal

        return Conversation, Message, SessionLocal

    @staticmethod
    def _serialize(state: ConversationState) -> dict:
        return state.model_dump(mode="json")

    def create(self, state: ConversationState) -> ConversationState:
        if state.owner_user_id is None:
            raise ConversationStoreError(
                "공통 대화를 만들려면 owner_user_id가 필요합니다."
            )

        Conversation, Message, SessionLocal = self._load_models()
        db = SessionLocal()
        try:
            stored = state.model_copy(deep=True)
            conversation = Conversation(
                user_id=stored.owner_user_id,
                part=self.part,
                title=None,
                state=None,
            )
            db.add(conversation)
            db.flush()

            stored.conversation_id = str(conversation.id)
            for document in stored.documents:
                document.conversation_id = stored.conversation_id

            for message in stored.messages:
                db.add(
                    Message(
                        conversation_id=conversation.id,
                        role=message.role.value,
                        content=message.content,
                    )
                )
            stored.persisted_message_count = len(stored.messages)
            stored.touch()
            conversation.state = self._serialize(stored)
            db.commit()
            return stored.model_copy(deep=True)
        except Exception as error:
            db.rollback()
            raise ConversationStoreError(
                "공통 conversations 테이블에 A파트 상담을 생성하지 못했습니다."
            ) from error
        finally:
            db.close()

    def get(self, conversation_id: str) -> ConversationState:
        conversation_pk = self._normalize_id(conversation_id)
        Conversation, _, SessionLocal = self._load_models()
        db = SessionLocal()
        try:
            row = (
                db.query(Conversation)
                .filter(
                    Conversation.id == conversation_pk,
                    Conversation.part == self.part,
                )
                .first()
            )
            if row is None or not row.state:
                raise ConversationNotFoundError(str(conversation_id))
            state = ConversationState.model_validate(row.state)
            state.conversation_id = str(row.id)
            state.owner_user_id = int(row.user_id)
            return state.model_copy(deep=True)
        finally:
            db.close()

    def save(self, state: ConversationState) -> ConversationState:
        conversation_pk = self._normalize_id(state.conversation_id)
        Conversation, Message, SessionLocal = self._load_models()
        db = SessionLocal()
        try:
            row = (
                db.query(Conversation)
                .filter(
                    Conversation.id == conversation_pk,
                    Conversation.part == self.part,
                )
                .first()
            )
            if row is None:
                raise ConversationNotFoundError(state.conversation_id)
            if state.owner_user_id is not None and row.user_id != state.owner_user_id:
                raise ConversationStoreError("상담 소유자가 일치하지 않습니다.")

            stored = state.model_copy(deep=True)
            persisted = min(
                stored.persisted_message_count,
                len(stored.messages),
            )
            for message in stored.messages[persisted:]:
                db.add(
                    Message(
                        conversation_id=conversation_pk,
                        role=message.role.value,
                        content=message.content,
                    )
                )
            stored.persisted_message_count = len(stored.messages)
            stored.owner_user_id = int(row.user_id)
            stored.touch()
            row.state = self._serialize(stored)

            from sqlalchemy import func

            row.updated_at = func.now()
            db.commit()
            return stored.model_copy(deep=True)
        except ConversationNotFoundError:
            raise
        except Exception as error:
            db.rollback()
            raise ConversationStoreError(
                "공통 conversations 테이블에 A파트 상담 상태를 저장하지 못했습니다."
            ) from error
        finally:
            db.close()

    def upsert(self, state: ConversationState) -> ConversationState:
        if self.exists(state.conversation_id):
            return self.save(state)
        return self.create(state)

    def delete(self, conversation_id: str) -> bool:
        conversation_pk = self._normalize_id(conversation_id)
        Conversation, Message, SessionLocal = self._load_models()
        db = SessionLocal()
        try:
            row = (
                db.query(Conversation)
                .filter(
                    Conversation.id == conversation_pk,
                    Conversation.part == self.part,
                )
                .first()
            )
            if row is None:
                return False
            db.query(Message).filter(
                Message.conversation_id == conversation_pk
            ).delete(synchronize_session=False)
            db.delete(row)
            db.commit()
            return True
        except Exception as error:
            db.rollback()
            raise ConversationStoreError(
                "공통 conversation을 삭제하지 못했습니다."
            ) from error
        finally:
            db.close()

    def reset(self, conversation_id: str) -> ConversationState:
        state = self.get(conversation_id)
        if not self.delete(conversation_id):
            raise ConversationNotFoundError(conversation_id)
        return state

    def clear(self) -> int:
        ids = self.list_ids()
        for conversation_id in ids:
            self.delete(conversation_id)
        return len(ids)

    def exists(self, conversation_id: str) -> bool:
        try:
            self.get(conversation_id)
            return True
        except ConversationNotFoundError:
            return False

    def count(self) -> int:
        Conversation, _, SessionLocal = self._load_models()
        db = SessionLocal()
        try:
            return int(
                db.query(Conversation)
                .filter(Conversation.part == self.part)
                .count()
            )
        finally:
            db.close()

    def list_ids(self) -> tuple[str, ...]:
        Conversation, _, SessionLocal = self._load_models()
        db = SessionLocal()
        try:
            rows = (
                db.query(Conversation.id)
                .filter(Conversation.part == self.part)
                .order_by(Conversation.updated_at.desc())
                .all()
            )
            return tuple(str(row[0]) for row in rows)
        finally:
            db.close()

    def list_for_owner(self, owner_user_id: int) -> list[dict]:
        """특정 사용자의 A파트 상담 목록을 최신순으로 반환한다."""

        Conversation, _, SessionLocal = self._load_models()
        db = SessionLocal()
        try:
            rows = (
                db.query(Conversation)
                .filter(
                    Conversation.part == self.part,
                    Conversation.user_id == owner_user_id,
                )
                .order_by(Conversation.updated_at.desc())
                .all()
            )
            summaries: list[dict] = []
            for row in rows:
                if not row.state:
                    continue
                try:
                    state = ConversationState.model_validate(row.state)
                except Exception:
                    continue
                summaries.append(
                    {
                        "conversation_id": str(row.id),
                        "title": row.title or state.initial_query or "새 계약 전 상담",
                        "risk_level": state.last_risk_level,
                        "turn_count": state.turn_count,
                        "created_at": state.created_at.isoformat() if state.created_at else None,
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    }
                )
            return summaries
        finally:
            db.close()
