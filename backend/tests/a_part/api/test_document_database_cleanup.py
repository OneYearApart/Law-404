from __future__ import annotations

from backend.app.documents.db_storage import DocumentDatabaseRepository


class FakeCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[str, ...]]] = []
        self.rowcount = 0
        self._fetchone = (0,)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: tuple[str, ...]) -> None:
        normalized = " ".join(sql.split())
        self.executed.append((normalized, params))

        if "DELETE FROM a_part_document_comparisons" in normalized:
            self.rowcount = 1
        elif "DELETE FROM a_part_document_analyses" in normalized:
            self.rowcount = 2
        elif "SELECT COUNT(*) FROM a_part_document_extractions" in normalized:
            self._fetchone = (3,)
            self.rowcount = 1
        elif "DELETE FROM a_part_documents" in normalized:
            self.rowcount = 4
        else:
            raise AssertionError(f"예상하지 못한 SQL입니다: {normalized}")

    def fetchone(self):
        return self._fetchone


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


def test_delete_conversation_artifacts_deletes_all_document_tables(monkeypatch):
    repository = DocumentDatabaseRepository("postgresql://test")
    cursor = FakeCursor()
    monkeypatch.setattr(repository, "connect", lambda: FakeConnection(cursor))

    result = repository.delete_conversation_artifacts(
        conversation_id="conversation-1"
    )

    assert result == {
        "documents": 4,
        "extractions": 3,
        "analyses": 2,
        "comparisons": 1,
    }

    executed_sql = [sql for sql, _ in cursor.executed]
    assert any("a_part_document_comparisons" in sql for sql in executed_sql)
    assert any("a_part_document_analyses" in sql for sql in executed_sql)
    assert any("a_part_document_extractions" in sql for sql in executed_sql)
    assert any("DELETE FROM a_part_documents" in sql for sql in executed_sql)
    assert all(params == ("conversation-1",) for _, params in cursor.executed)
