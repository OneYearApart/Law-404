from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_user
from app.main import app
from app.api.routes.a_part import get_a_part_chatbot_service
from app.consultation.a_part.chatbot_service import APartChatbotService
from app.consultation.a_part.document_service import APartDocumentUploadService
from app.consultation.a_part.service import APartConversationService
from app.consultation.a_part.state_updater import SlotExtractionResult
from app.consultation.a_part.store import MemoryConversationStore
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
    return APartRAGResponse(
        query=query,
        answer_code_version="test-answer",
        consultation_context=(
            consultation_context
            if isinstance(consultation_context, ConsultationContext)
            else ConsultationContext(known_facts=consultation_context.known_facts)
        ),
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
        search_code_version="test-search",
    )


class TrackingDatabaseRepository:
    def __init__(self):
        self.documents: dict[str, str] = {}
        self.states: set[str] = set()
        self.analyses: set[str] = set()
        self.comparisons: set[str] = set()

    def upsert_document(self, *, document_id, conversation_id, **kwargs):
        self.documents[document_id] = conversation_id

    def upsert_state(self, *, conversation_id, state):
        self.states.add(conversation_id)

    def delete_document(self, *, conversation_id, document_id):
        return self.documents.pop(document_id, None) == conversation_id

    def delete_conversation_artifacts(self, *, conversation_id):
        document_ids = [
            document_id
            for document_id, owner_id in self.documents.items()
            if owner_id == conversation_id
        ]
        for document_id in document_ids:
            self.documents.pop(document_id, None)

        analyses = int(conversation_id in self.analyses)
        comparisons = int(conversation_id in self.comparisons)
        self.analyses.discard(conversation_id)
        self.comparisons.discard(conversation_id)

        return {
            "documents": len(document_ids),
            "extractions": 0,
            "analyses": analyses,
            "comparisons": comparisons,
        }


def build_service(tmp_path, *, database_repository=None):
    store = MemoryConversationStore()
    conversation_service = APartConversationService(
        store=store,
        slot_extractor=EmptySlotExtractor(),
        rag_answerer=fake_rag_answerer,
    )
    upload_service = DocumentUploadService(storage_root=tmp_path / "uploads")
    document_service = APartDocumentUploadService(
        upload_service=upload_service,
        conversation_service=conversation_service,
        database_repository=database_repository,
    )
    return APartChatbotService(
        conversation_service=conversation_service,
        document_service=document_service,
    )


def test_a_part_api_normal_and_exception_flows(tmp_path):
    service = build_service(tmp_path)
    current_user = {"id": 1}

    def override_user():
        return SimpleNamespace(id=current_user["id"])

    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_a_part_chatbot_service] = lambda: service

    try:
        with TestClient(app) as client:
            created = client.post("/chat/a/conversations", json={})
            assert created.status_code == 201
            conversation_id = created.json()["data"]["conversation_id"]
            assert created.json()["data"]["owner_user_id"] == 1

            empty = client.post("/chat/a/turn", json={"question": "   "})
            assert empty.status_code == 422
            assert empty.json()["error"]["code"] == "EMPTY_CHAT_INPUT"

            unclear = client.post("/chat/a/turn", json={"question": "ㅋㅋㅋㅋ"})
            assert unclear.status_code == 422
            assert unclear.json()["error"]["code"] == "UNCLEAR_CHAT_INPUT"

            out_of_scope = client.post(
                "/chat/a/turn",
                json={"question": "오늘 저녁 메뉴를 추천해 주세요."},
            )
            assert out_of_scope.status_code == 422
            assert out_of_scope.json()["error"]["code"] == "OUT_OF_SCOPE_QUERY"

            document_required = client.post(
                "/chat/a/turn",
                json={"question": "계약서 검토해 주세요."},
            )
            assert document_required.status_code == 422
            assert document_required.json()["error"]["code"] == "DOCUMENT_REQUIRED"

            valid = client.post(
                "/chat/a/turn",
                json={"question": "등기부등본에 근저당이 있는데 계약해도 되나요?"},
            )
            assert valid.status_code == 200
            valid_payload = valid.json()["data"]
            assert valid_payload["answer_ready"] is True
            assert valid_payload["consultation"]["state"]["owner_user_id"] == 1

            wrong_type = client.post(
                f"/chat/a/conversations/{conversation_id}/documents?extract_text=false",
                data={"document_type": "transfer_receipt"},
                files={"file": ("receipt.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
            )
            assert wrong_type.status_code == 415
            assert wrong_type.json()["error"]["code"] == "UNSUPPORTED_DOCUMENT_TYPE"

            invalid_pdf = client.post(
                f"/chat/a/conversations/{conversation_id}/documents?extract_text=false",
                data={"document_type": "lease_contract"},
                files={"file": ("lease.pdf", b"not a pdf", "application/pdf")},
            )
            assert invalid_pdf.status_code == 415
            assert invalid_pdf.json()["error"]["code"] == "INVALID_DOCUMENT"

            uploaded = client.post(
                f"/chat/a/conversations/{conversation_id}/documents?extract_text=false",
                data={"document_type": "lease_contract"},
                files={"file": ("lease.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
            )
            assert uploaded.status_code == 201
            assert uploaded.json()["data"]["upload"]["document"]["document_type"] == "lease_contract"

            listed = client.get(
                f"/chat/a/conversations/{conversation_id}/documents"
            )
            assert listed.status_code == 200
            assert len(listed.json()["data"]) == 1
            document_id = listed.json()["data"][0]["document_id"]

            removed = client.delete(
                f"/chat/a/conversations/{conversation_id}/documents/{document_id}"
            )
            assert removed.status_code == 200
            assert removed.json()["data"]["document_id"] == document_id

            listed_after_delete = client.get(
                f"/chat/a/conversations/{conversation_id}/documents"
            )
            assert listed_after_delete.status_code == 200
            assert listed_after_delete.json()["data"] == []

            missing_question = client.post("/chat/a/turn", json={})
            assert missing_question.status_code == 422
            assert missing_question.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"

            current_user["id"] = 2
            denied = client.get(f"/chat/a/conversations/{conversation_id}")
            assert denied.status_code == 403
            assert denied.json()["error"]["code"] == "CONVERSATION_ACCESS_DENIED"
    finally:
        app.dependency_overrides.clear()


def test_a_part_api_extracts_text_layer_pdf(tmp_path):
    import fitz

    service = build_service(tmp_path)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
    app.dependency_overrides[get_a_part_chatbot_service] = lambda: service

    pdf = fitz.open()
    page = pdf.new_page()
    text = "LEASE CONTRACT\n" + "\n".join(
        f"Clause {index}: deposit and payment schedule information."
        for index in range(1, 30)
    )
    page.insert_textbox(fitz.Rect(50, 50, 550, 780), text, fontsize=9)
    pdf_bytes = pdf.tobytes()
    pdf.close()

    try:
        with TestClient(app) as client:
            created = client.post("/chat/a/conversations", json={})
            conversation_id = created.json()["data"]["conversation_id"]

            uploaded = client.post(
                f"/chat/a/conversations/{conversation_id}/documents",
                data={"document_type": "lease_contract"},
                files={"file": ("lease.pdf", pdf_bytes, "application/pdf")},
            )
            assert uploaded.status_code == 201
            extraction = uploaded.json()["data"]["extraction"]["extraction"]
            assert extraction["processing_status"] == "completed"
            assert extraction["page_count"] == 1
            assert extraction["direct_text_page_count"] == 1
            assert extraction["ocr_page_count"] == 0
            assert extraction["text_character_count"] > 500
    finally:
        app.dependency_overrides.clear()


def test_delete_conversation_removes_files_state_and_database_artifacts(tmp_path):
    database_repository = TrackingDatabaseRepository()
    service = build_service(
        tmp_path,
        database_repository=database_repository,
    )

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=11)
    app.dependency_overrides[get_a_part_chatbot_service] = lambda: service

    try:
        with TestClient(app) as client:
            created = client.post("/chat/a/conversations", json={})
            assert created.status_code == 201
            conversation_id = created.json()["data"]["conversation_id"]

            for document_type, filename, pdf_bytes in (
                (
                    "lease_contract",
                    "lease.pdf",
                    b"%PDF-1.4\n% lease contract\n%%EOF",
                ),
                (
                    "registry",
                    "registry.pdf",
                    b"%PDF-1.4\n% registry document\n%%EOF",
                ),
            ):
                uploaded = client.post(
                    f"/chat/a/conversations/{conversation_id}/documents?extract_text=false",
                    data={"document_type": document_type},
                    files={
                        "file": (
                            filename,
                            pdf_bytes,
                            "application/pdf",
                        )
                    },
                )
                assert uploaded.status_code == 201

            database_repository.analyses.add(conversation_id)
            database_repository.comparisons.add(conversation_id)

            conversation_directory = tmp_path / "uploads" / conversation_id
            assert conversation_directory.exists()
            assert len(database_repository.documents) == 2
            assert service.conversation_service.get_state(conversation_id)

            deleted = client.delete(
                f"/chat/a/conversations/{conversation_id}"
            )
            assert deleted.status_code == 200

            payload = deleted.json()["data"]
            assert payload["deleted"] is True
            assert payload["warnings"] == []
            assert payload["cleanup"]["deleted_file_count"] == 2
            assert payload["cleanup"]["database_cleanup"] == {
                "documents": 2,
                "extractions": 0,
                "analyses": 1,
                "comparisons": 1,
            }

            assert not conversation_directory.exists()
            assert database_repository.documents == {}
            assert conversation_id not in database_repository.analyses
            assert conversation_id not in database_repository.comparisons

            missing = client.get(
                f"/chat/a/conversations/{conversation_id}"
            )
            assert missing.status_code == 404
            assert (
                missing.json()["error"]["code"]
                == "CONVERSATION_NOT_FOUND"
            )
    finally:
        app.dependency_overrides.clear()
