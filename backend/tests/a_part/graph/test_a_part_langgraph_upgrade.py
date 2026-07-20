from __future__ import annotations

from pathlib import Path

import pytest

from app.consultation.a_part.chatbot_service import ChatbotTurnRequest
from app.consultation.a_part.models import create_conversation_state
from app.documents.analysis.models import ConversationDocumentAnalysisResponse
from app.documents.models import DocumentFormat, DocumentType, UploadedDocument
from tests.a_part.api.test_a_part_api import build_service


REPRESENTATIVE_QUESTIONS = [
    ("q01_owner_proxy", "집주인 아들이 대신 계약하러 왔는데 위임장이 없어요."),
    ("q02_co_owner", "공동명의 집인데 소유자 한 명만 계약하러 왔어요."),
    ("q03_owner_lessor_mismatch", "등기부 소유자와 계약서 임대인 이름이 달라요."),
    ("q04_broker_account_payment", "중개사 명의 계좌로 계약금을 보내라고 해요."),
    ("q05_account_change_before_contract", "계약 직전에 계약금 계좌가 바뀌었다고 합니다."),
    ("q06_broker_explanation_mismatch", "중개대상물 확인설명서와 계약서 내용이 달라요."),
    ("q07_mortgage", "등기부에 근저당과 채권최고액이 있어요."),
    ("q08_multiunit_priority", "다가구주택인데 선순위 보증금을 확인 못했어요."),
    ("q09_registry_restriction_warning", "등기부에 가압류가 있는데 계약해도 되나요?"),
    ("q10_trust", "신탁등기가 있는 집인데 임대차 계약을 해도 되나요?"),
    ("q11_opposability_move_in", "전입신고를 하면 대항력은 언제 생기나요?"),
    ("q12_fixed_date_priority", "확정일자와 우선변제권이 궁금해요."),
    ("q13_owner_change", "계약 후 집주인이 바뀌었다고 해요."),
    ("q14_special_clause_deposit_return", "계약금을 돌려받는 특약을 넣고 싶어요."),
    ("q15_after_contract_procedure", "계약서 작성 직후 무엇부터 해야 하나요?"),
    ("q16_lease_report", "주택 임대차신고는 언제 해야 하나요?"),
    ("q17_household_certificate", "전입세대확인서는 왜 확인해야 하나요?"),
    ("q18_address_mismatch", "계약서 주소와 등기부등본 주소가 달라요."),
    ("q19_deposit_transfer_mismatch", "계약서 보증금과 실제 이체 내역 금액이 달라요."),
    ("q20_guarantee_check", "전세보증금반환보증 가입 전에 뭘 확인해야 하나요?"),
]


@pytest.mark.parametrize(("expected_issue_id", "question"), REPRESENTATIVE_QUESTIONS)
def test_all_twenty_questions_enter_langgraph(
    tmp_path: Path,
    expected_issue_id: str,
    question: str,
):
    service = build_service(tmp_path)

    result = service.handle(ChatbotTurnRequest(question=question))

    assert result.consultation.primary_issue_id == expected_issue_id
    assert result.orchestration["framework"] == "langgraph"
    assert result.orchestration["graph_version"] == "a-part-langgraph-v1"
    assert result.orchestration["document_mode"] == "general"
    assert result.answer_ready is True


def test_owner_proxy_keeps_one_follow_up_question_per_turn(tmp_path: Path):
    service = build_service(tmp_path)

    first = service.handle(
        ChatbotTurnRequest(question="집주인 가족이 대신 계약하러 왔어요.")
    )
    assert len(first.consultation.follow_up_questions) == 1

    second = service.handle(
        ChatbotTurnRequest(
            question="등기부 소유자는 김철수입니다.",
            conversation_id=first.conversation_id,
        )
    )

    assert len(second.consultation.follow_up_questions) <= 1
    assert second.orchestration["route_engine"] == "active_issue"
    assert second.consultation.primary_issue_id == "q01_owner_proxy"


def _document(
    *,
    conversation_id: str,
    document_id: str,
    document_type: DocumentType,
) -> UploadedDocument:
    filename = "lease.pdf" if document_type == DocumentType.LEASE_CONTRACT else "registry.pdf"
    return UploadedDocument(
        document_id=document_id,
        conversation_id=conversation_id,
        document_type=document_type,
        original_filename=filename,
        safe_filename=filename,
        stored_filename=filename,
        stored_path=f"{conversation_id}/{filename}",
        detected_format=DocumentFormat.PDF,
        content_type="application/pdf",
        size_bytes=100,
        sha256="a" * 64,
    )


@pytest.mark.parametrize(
    ("document_types", "expected_mode"),
    [
        ([DocumentType.LEASE_CONTRACT], "lease_contract"),
        ([DocumentType.REGISTRY], "registry"),
        (
            [DocumentType.LEASE_CONTRACT, DocumentType.REGISTRY],
            "combined_documents",
        ),
    ],
)
def test_document_types_use_separate_langgraph_branches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    document_types: list[DocumentType],
    expected_mode: str,
):
    service = build_service(tmp_path)
    state = create_conversation_state("q15_after_contract_procedure")
    stored = service.conversation_service.store.create(state)

    document_ids: list[str] = []
    for index, document_type in enumerate(document_types, start=1):
        document_id = f"doc-{index}"
        document_ids.append(document_id)
        service.conversation_service.attach_document(
            stored.conversation_id,
            _document(
                conversation_id=stored.conversation_id,
                document_id=document_id,
                document_type=document_type,
            ),
        )

    def fake_analyze_documents(**kwargs):
        current = service.conversation_service.get_state(stored.conversation_id)
        return ConversationDocumentAnalysisResponse(state=current)

    monkeypatch.setattr(
        service.document_service,
        "analyze_documents",
        fake_analyze_documents,
    )

    question = (
        "첨부한 계약서와 등기부등본을 분석해 주세요."
        if len(document_types) == 2
        else (
            "첨부한 계약서를 분석해 주세요."
            if document_types[0] == DocumentType.LEASE_CONTRACT
            else "첨부한 등기부등본을 분석해 주세요."
        )
    )
    result = service.handle(
        ChatbotTurnRequest(
            question=question,
            conversation_id=stored.conversation_id,
            document_ids=document_ids,
            analyze_documents=True,
        )
    )

    assert result.orchestration["framework"] == "langgraph"
    assert result.orchestration["document_mode"] == expected_mode
    assert result.document_analysis is not None

def test_langchain_route_and_search_plan_use_structured_runnables(monkeypatch):
    from langchain_core.runnables import RunnableLambda

    from app.graph.parts.a_part import chains
    from app.graph.parts.a_part.schemas import APartRouteDecision, APartSearchPlan

    class FakeChatModel:
        def with_structured_output(self, schema, **kwargs):
            if schema is APartRouteDecision:
                return RunnableLambda(
                    lambda value: APartRouteDecision(
                        in_scope=True,
                        primary_issue_id="q07_mortgage",
                        related_issue_ids=[],
                        confidence=0.95,
                        search_query="근저당 채권최고액과 보증금 보호 기준",
                        reason="테스트 분류",
                    )
                )
            return RunnableLambda(
                lambda value: APartSearchPlan(
                    query_override="근저당 채권최고액과 잔금 전 최신 등기부 확인 기준",
                    focus_terms=["근저당", "채권최고액"],
                    reason="테스트 검색 계획",
                )
            )

    monkeypatch.setattr(chains, "_chat_model", lambda **kwargs: FakeChatModel())

    decision, route_engine = chains.route_question(
        "등기부에 은행 근저당이 있는데 계약해도 되나요?",
        use_langchain=True,
    )
    query, planner_engine = chains.plan_search_query(
        user_question="등기부에 은행 근저당이 있는데 계약해도 되나요?",
        route_decision=decision,
        known_facts=[],
        document_context=None,
        fallback_query=decision.search_query,
        use_langchain=True,
    )

    assert route_engine == "langchain"
    assert decision.primary_issue_id == "q07_mortgage"
    assert planner_engine == "langchain"
    assert "최신 등기부" in query

