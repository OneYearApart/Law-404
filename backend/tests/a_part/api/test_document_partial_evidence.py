from app.consultation.a_part.chatbot_service import APartChatbotService
from app.consultation.a_part.service import APartConversationService
from app.consultation.a_part.state_updater import SlotExtractionResult
from app.consultation.a_part.store import MemoryConversationStore
from app.documents.analysis.models import ConversationDocumentAnalysisResponse
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


def evidence_not_found_answerer(*, query, consultation_context, **kwargs):
    return APartRAGResponse(
        query=query,
        answer_code_version="test",
        consultation_context=(
            consultation_context
            if isinstance(consultation_context, ConsultationContext)
            else ConsultationContext(known_facts=consultation_context.known_facts)
        ),
        evidence_status=EvidenceStatus.INSUFFICIENT,
        generation_status=RAGGenerationStatus.EVIDENCE_NOT_FOUND,
        answer=APartAnswer(
            risk_level="확인 필요",
            core_judgment="RAG 근거를 찾지 못했습니다.",
            immediate_actions=["다시 검색합니다."],
            hold_actions=[],
            reasons=[],
            required_information=[],
            references=[],
            follow_up_questions=[],
        ),
        selected_evidence=[],
        search_result_count=0,
    )


def test_document_result_remains_answerable_when_rag_evidence_is_missing():
    conversation_service = APartConversationService(
        store=MemoryConversationStore(),
        slot_extractor=EmptySlotExtractor(),
        rag_answerer=evidence_not_found_answerer,
    )
    chatbot = APartChatbotService(conversation_service=conversation_service)
    consultation = conversation_service.handle(
        "계약서와 등기부등본을 검토해 주세요.",
        issue_id="q15_after_contract_procedure",
    )

    updated = chatbot._apply_document_summary(
        consultation,
        ConversationDocumentAnalysisResponse(),
    )

    assert updated.answer_ready is True
    assert updated.rag_generation_status == "partial_evidence"
    assert updated.rag_response.generation_status.value == "partial_evidence"
    assert updated.rag_response.evidence_status.value == "partial"
    assert "첨부 문서 기준" in updated.rag_response.answer.core_judgment
