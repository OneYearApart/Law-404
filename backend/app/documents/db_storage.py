"""사용자 문서 원본·추출·분석 결과를 PostgreSQL에 저장한다."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable



DEFAULT_DATABASE_URL = (
    os.getenv("LAW404_DATABASE_URL")
    or os.getenv("DATABASE_URL")
    or ""
)


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _psycopg2_modules():
    try:
        import psycopg2
        from psycopg2 import Binary
        from psycopg2.extras import Json
    except ImportError as error:
        raise RuntimeError(
            "PostgreSQL 저장에는 psycopg2-binary가 필요합니다."
        ) from error
    return psycopg2, Binary, Json


def _json(value: Any):
    _, _, Json = _psycopg2_modules()
    return Json(
        value,
        dumps=lambda item: json.dumps(item, ensure_ascii=False),
    )


class DocumentDatabaseRepository:
    """실문서 검증 결과를 기존 edudb의 A파트 테이블에 저장한다."""

    def __init__(self, database_url: str | None = None) -> None:
        resolved = database_url or DEFAULT_DATABASE_URL
        if not resolved:
            raise ValueError(
                "DB 접속 문자열이 없습니다. "
                "LAW404_DATABASE_URL 또는 DATABASE_URL을 지정하세요."
            )
        self.database_url = resolved

    def connect(self):
        psycopg2, _, _ = _psycopg2_modules()
        return psycopg2.connect(self.database_url)

    def ensure_schema(self, schema_path: Path) -> None:
        sql = schema_path.read_text(encoding="utf-8")
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)

    def reset_validation_conversations(
        self,
        conversation_ids: Iterable[str],
    ) -> None:
        ids = list(conversation_ids)
        if not ids:
            return
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM a_part_conversation_states WHERE conversation_id = ANY(%s)",
                    (ids,),
                )
                cursor.execute(
                    "DELETE FROM a_part_document_comparisons WHERE conversation_id = ANY(%s)",
                    (ids,),
                )
                cursor.execute(
                    "DELETE FROM a_part_document_analyses WHERE conversation_id = ANY(%s)",
                    (ids,),
                )
                cursor.execute(
                    "DELETE FROM a_part_documents WHERE conversation_id = ANY(%s)",
                    (ids,),
                )

    def upsert_document(
        self,
        *,
        document_id: str,
        conversation_id: str,
        source_type: str,
        document_type: str,
        page_index: int,
        original_filename: str,
        content_type: str,
        data: bytes,
        sha256: str,
    ) -> None:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO a_part_documents (
                        document_id,
                        conversation_id,
                        source_type,
                        document_type,
                        page_index,
                        original_filename,
                        content_type,
                        size_bytes,
                        sha256,
                        original_bytes
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (document_id) DO UPDATE SET
                        conversation_id = EXCLUDED.conversation_id,
                        source_type = EXCLUDED.source_type,
                        document_type = EXCLUDED.document_type,
                        page_index = EXCLUDED.page_index,
                        original_filename = EXCLUDED.original_filename,
                        content_type = EXCLUDED.content_type,
                        size_bytes = EXCLUDED.size_bytes,
                        sha256 = EXCLUDED.sha256,
                        original_bytes = EXCLUDED.original_bytes,
                        updated_at = NOW()
                    """,
                    (
                        document_id,
                        conversation_id,
                        source_type,
                        document_type,
                        page_index,
                        original_filename,
                        content_type,
                        len(data),
                        sha256,
                        _psycopg2_modules()[1](data),
                    ),
                )

    def upsert_extraction(self, extraction: Any) -> None:
        payload = _json_value(extraction)
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO a_part_document_extractions (
                        document_id,
                        extraction_version,
                        processing_status,
                        extraction_method,
                        page_count,
                        successful_page_count,
                        failed_page_count,
                        direct_text_page_count,
                        ocr_page_count,
                        text_character_count,
                        average_ocr_confidence,
                        combined_text,
                        pages,
                        warnings,
                        errors,
                        started_at,
                        completed_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (document_id, extraction_version) DO UPDATE SET
                        processing_status = EXCLUDED.processing_status,
                        extraction_method = EXCLUDED.extraction_method,
                        page_count = EXCLUDED.page_count,
                        successful_page_count = EXCLUDED.successful_page_count,
                        failed_page_count = EXCLUDED.failed_page_count,
                        direct_text_page_count = EXCLUDED.direct_text_page_count,
                        ocr_page_count = EXCLUDED.ocr_page_count,
                        text_character_count = EXCLUDED.text_character_count,
                        average_ocr_confidence = EXCLUDED.average_ocr_confidence,
                        combined_text = EXCLUDED.combined_text,
                        pages = EXCLUDED.pages,
                        warnings = EXCLUDED.warnings,
                        errors = EXCLUDED.errors,
                        started_at = EXCLUDED.started_at,
                        completed_at = EXCLUDED.completed_at,
                        updated_at = NOW()
                    """,
                    (
                        payload["document_id"],
                        payload["extraction_version"],
                        payload["processing_status"],
                        payload["extraction_method"],
                        payload["page_count"],
                        payload["successful_page_count"],
                        payload["failed_page_count"],
                        payload["direct_text_page_count"],
                        payload["ocr_page_count"],
                        payload["text_character_count"],
                        payload.get("average_ocr_confidence"),
                        payload.get("combined_text", ""),
                        _json(payload.get("pages", [])),
                        _json(payload.get("warnings", [])),
                        _json(payload.get("errors", [])),
                        payload.get("started_at"),
                        payload.get("completed_at"),
                    ),
                )

    def upsert_analysis(
        self,
        *,
        conversation_id: str,
        source_type: str,
        document_type: str,
        analysis_version: str,
        source_document_ids: list[str],
        result: Any,
    ) -> None:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO a_part_document_analyses (
                        conversation_id,
                        source_type,
                        document_type,
                        analysis_version,
                        source_document_ids,
                        result
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (
                        conversation_id,
                        source_type,
                        document_type,
                        analysis_version
                    ) DO UPDATE SET
                        source_document_ids = EXCLUDED.source_document_ids,
                        result = EXCLUDED.result,
                        updated_at = NOW()
                    """,
                    (
                        conversation_id,
                        source_type,
                        document_type,
                        analysis_version,
                        _json(source_document_ids),
                        _json(_json_value(result)),
                    ),
                )

    def upsert_comparison(
        self,
        *,
        conversation_id: str,
        source_type: str,
        analysis_version: str,
        result: Any,
    ) -> None:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO a_part_document_comparisons (
                        conversation_id,
                        source_type,
                        analysis_version,
                        result
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (conversation_id, source_type, analysis_version)
                    DO UPDATE SET
                        result = EXCLUDED.result,
                        updated_at = NOW()
                    """,
                    (
                        conversation_id,
                        source_type,
                        analysis_version,
                        _json(_json_value(result)),
                    ),
                )

    def upsert_state(self, *, conversation_id: str, state: Any) -> None:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO a_part_conversation_states (
                        conversation_id,
                        state
                    ) VALUES (%s, %s)
                    ON CONFLICT (conversation_id) DO UPDATE SET
                        state = EXCLUDED.state,
                        updated_at = NOW()
                    """,
                    (
                        conversation_id,
                        _json(_json_value(state)),
                    ),
                )

    def counts(self) -> dict[str, int]:
        tables = (
            "a_part_documents",
            "a_part_document_extractions",
            "a_part_document_analyses",
            "a_part_document_comparisons",
            "a_part_conversation_states",
        )
        result: dict[str, int] = {}
        with self.connect() as conn:
            with conn.cursor() as cursor:
                for table in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    result[table] = int(cursor.fetchone()[0])
        return result
