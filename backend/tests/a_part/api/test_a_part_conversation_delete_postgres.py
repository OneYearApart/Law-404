from __future__ import annotations

import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

if os.getenv("RUN_POSTGRES_INTEGRATION_TESTS") != "1":
    pytest.skip(
        "RUN_POSTGRES_INTEGRATION_TESTS=1일 때만 실제 PostgreSQL 삭제 테스트를 실행합니다.",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient

from app.api.routes.a_part import get_a_part_chatbot_service
from app.auth.dependencies import get_current_user
from app.main import app
from app.consultation.a_part.chatbot_service import APartChatbotService
from app.consultation.a_part.document_service import APartDocumentUploadService
from app.consultation.a_part.service import APartConversationService
from app.consultation.a_part.state_updater import SlotExtractionResult
from app.consultation.a_part.store import PostgresConversationStore
from app.core.config import settings
from app.documents.db_storage import DocumentDatabaseRepository
from app.documents.service import DocumentUploadService
from app.llm.a_part import (
    APartAnswer,
    APartRAGResponse,
    ConsultationContext,
    EvidenceStatus,
    RAGGenerationStatus,
)


class EmptySlotExtractor:
    def extract(self, *, user_text, state):
        return SlotExtractionResult()


def fake_rag_answerer(*, query, consultation_context, **kwargs):
    context = (
        consultation_context
        if isinstance(consultation_context, ConsultationContext)
        else ConsultationContext(known_facts=consultation_context.known_facts)
    )
    return APartRAGResponse(
        query=query,
        answer_code_version="postgres-delete-test",
        consultation_context=context,
        evidence_status=EvidenceStatus.SUFFICIENT,
        generation_status=RAGGenerationStatus.COMPLETED,
        answer=APartAnswer(
            risk_level="확인 필요",
            core_judgment="테스트 답변입니다.",
            immediate_actions=["관련 자료를 확인합니다."],
            hold_actions=[],
            reasons=["테스트 근거"],
            required_information=[],
            references=[],
            follow_up_questions=[],
        ),
        selected_evidence=[],
        search_result_count=1,
        search_code_version="postgres-delete-test",
    )


def _conversation_counts(repository, conversation_id: str) -> dict[str, int]:
    with repository.connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM a_part_documents WHERE conversation_id = %s",
                (conversation_id,),
            )
            documents = int(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM a_part_document_extractions AS extraction
                JOIN a_part_documents AS document
                  ON document.document_id = extraction.document_id
                WHERE document.conversation_id = %s
                """,
                (conversation_id,),
            )
            extractions = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COUNT(*) FROM a_part_document_analyses WHERE conversation_id = %s",
                (conversation_id,),
            )
            analyses = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COUNT(*) FROM a_part_document_comparisons WHERE conversation_id = %s",
                (conversation_id,),
            )
            comparisons = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COUNT(*) FROM a_part_conversation_states WHERE conversation_id = %s",
                (conversation_id,),
            )
            states = int(cursor.fetchone()[0])
    return {
        "documents": documents,
        "extractions": extractions,
        "analyses": analyses,
        "comparisons": comparisons,
        "states": states,
    }


def test_delete_conversation_cleans_real_postgres_rows_and_files(tmp_path):
    database_url = os.getenv("LAW404_TEST_DATABASE_URL") or settings.database_url
    repository = DocumentDatabaseRepository(database_url)
    schema_path = (
        Path(__file__).resolve().parents[3]
        / "app"
        / "db"
        / "schema"
        / "a_part_document_tables.sql"
    )
    repository.ensure_schema(schema_path)

    conversation_store = PostgresConversationStore(database_url)
    conversation_service = APartConversationService(
        store=conversation_store,
        slot_extractor=EmptySlotExtractor(),
        rag_answerer=fake_rag_answerer,
    )
    upload_root = tmp_path / "uploads"
    document_service = APartDocumentUploadService(
        upload_service=DocumentUploadService(storage_root=upload_root),
        conversation_service=conversation_service,
        database_repository=repository,
    )
    service = APartChatbotService(
        conversation_service=conversation_service,
        document_service=document_service,
    )

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=901)
    app.dependency_overrides[get_a_part_chatbot_service] = lambda: service

    conversation_id = None
    try:
        with TestClient(app) as client:
            created = client.post("/chat/a/conversations", json={})
            assert created.status_code == 201
            conversation_id = created.json()["data"]["conversation_id"]

            uploaded = client.post(
                f"/chat/a/conversations/{conversation_id}/documents?extract_text=false",
                data={"document_type": "lease_contract"},
                files={
                    "file": (
                        "lease.pdf",
                        b"%PDF-1.4\n% postgres delete integration\n%%EOF",
                        "application/pdf",
                    )
                },
            )
            assert uploaded.status_code == 201
            document_id = uploaded.json()["data"]["upload"]["document"]["document_id"]

            with repository.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO a_part_document_extractions (
                            document_id, extraction_version, processing_status,
                            extraction_method, page_count, successful_page_count,
                            failed_page_count, direct_text_page_count, ocr_page_count,
                            text_character_count, combined_text, pages, warnings, errors
                        ) VALUES (
                            %s, 'delete-test-v1', 'completed', 'direct_text',
                            1, 1, 0, 1, 0, 10, 'test text',
                            '[]'::jsonb, '[]'::jsonb, '[]'::jsonb
                        )
                        """,
                        (document_id,),
                    )
                    cursor.execute(
                        """
                        INSERT INTO a_part_document_analyses (
                            conversation_id, source_type, document_type,
                            analysis_version, source_document_ids, result
                        ) VALUES (
                            %s, 'pdf', 'lease_contract', 'delete-test-v1',
                            %s::jsonb, '{}'::jsonb
                        )
                        """,
                        (conversation_id, f'["{document_id}"]'),
                    )
                    cursor.execute(
                        """
                        INSERT INTO a_part_document_comparisons (
                            conversation_id, source_type, analysis_version, result
                        ) VALUES (%s, 'pdf', 'delete-test-v1', '{}'::jsonb)
                        """,
                        (conversation_id,),
                    )

            assert _conversation_counts(repository, conversation_id) == {
                "documents": 1,
                "extractions": 1,
                "analyses": 1,
                "comparisons": 1,
                "states": 1,
            }
            assert (upload_root / conversation_id).exists()

            deleted = client.delete(f"/chat/a/conversations/{conversation_id}")
            assert deleted.status_code == 200
            payload = deleted.json()["data"]
            assert payload["deleted"] is True
            assert payload["cleanup"]["deleted_file_count"] == 1
            assert payload["cleanup"]["database_cleanup"] == {
                "documents": 1,
                "extractions": 1,
                "analyses": 1,
                "comparisons": 1,
            }

            assert _conversation_counts(repository, conversation_id) == {
                "documents": 0,
                "extractions": 0,
                "analyses": 0,
                "comparisons": 0,
                "states": 0,
            }
            assert not (upload_root / conversation_id).exists()
    finally:
        app.dependency_overrides.clear()
        if conversation_id:
            repository.reset_validation_conversations([conversation_id])
        shutil.rmtree(upload_root, ignore_errors=True)
