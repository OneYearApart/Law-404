"""사용자 문서 원본·추출·분석 결과를 PostgreSQL에 저장한다."""

from __future__ import annotations

import json
import os
from typing import Any

DEFAULT_DATABASE_URL = (
    os.getenv("LAW404_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
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

    def delete_document(
        self,
        *,
        conversation_id: str,
        document_id: str,
    ) -> bool:
        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM a_part_documents
                    WHERE conversation_id = %s AND document_id = %s
                    """,
                    (conversation_id, document_id),
                )
                return bool(cursor.rowcount)

    def delete_conversation_artifacts(
        self,
        *,
        conversation_id: str,
    ) -> dict[str, int]:
        """상담의 문서 원본·추출·분석·비교 결과를 한 트랜잭션에서 삭제한다."""

        normalized = str(conversation_id or "").strip()
        if not normalized:
            raise ValueError("conversation_id는 빈 문자열일 수 없습니다.")

        with self.connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM a_part_document_comparisons
                    WHERE conversation_id = %s
                    """,
                    (normalized,),
                )
                comparisons = int(cursor.rowcount)

                cursor.execute(
                    """
                    DELETE FROM a_part_document_analyses
                    WHERE conversation_id = %s
                    """,
                    (normalized,),
                )
                analyses = int(cursor.rowcount)

                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM a_part_document_extractions AS extraction
                    JOIN a_part_documents AS document
                      ON document.document_id = extraction.document_id
                    WHERE document.conversation_id = %s
                    """,
                    (normalized,),
                )
                extractions = int(cursor.fetchone()[0])

                cursor.execute(
                    """
                    DELETE FROM a_part_documents
                    WHERE conversation_id = %s
                    """,
                    (normalized,),
                )
                documents = int(cursor.rowcount)

        return {
            "documents": documents,
            "extractions": extractions,
            "analyses": analyses,
            "comparisons": comparisons,
        }

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
