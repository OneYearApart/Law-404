from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pydantic import BaseModel, Field

from backend.app.consultation.a_part.models import SlotStatus, create_conversation_state
from backend.app.consultation.a_part.question_builder import build_follow_up_questions
from backend.app.consultation.a_part.router import route_issues
from backend.app.consultation.a_part.service import APartConversationService, ConversationRAGContext
from backend.app.consultation.a_part.state_updater import ExtractedSlotUpdate, apply_slot_updates
from backend.app.consultation.a_part.store import ConversationNotFoundError, MemoryConversationStore


class FakeAnswer(BaseModel):
    risk_level: str
    core_judgment: str
    immediate_actions: list[str] = Field(default_factory=list)
    hold_actions: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    required_information: list[str] = Field(default_factory=list)
    references: list[dict[str, Any]] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    confirmation_message: str | None = None


class FakeRAGResponse(BaseModel):
    query: str
    answer_code_version: str
    consultation_context: ConversationRAGContext
    evidence_status: str
    answer: FakeAnswer
    selected_evidence: list[dict[str, Any]] = Field(default_factory=list)
    search_result_count: int
    search_code_version: str | None = None


def fake_rag_answerer(*, query: str, consultation_context: ConversationRAGContext, **_: object) -> FakeRAGResponse:
    return FakeRAGResponse(
        query=query,
        answer_code_version="conversation-state-test",
        consultation_context=consultation_context,
        evidence_status="sufficient",
        answer=FakeAnswer(
            risk_level="진행 보류 권장",
            core_judgment="기본 RAG 판단",
            immediate_actions=["필요한 권한과 자료를 확인하세요."],
            hold_actions=["계약서 서명", "계약금 송금"],
            reasons=["확인되지 않은 권한이 있습니다."],
            follow_up_questions=["기본 추가 질문"],
        ),
        search_result_count=3,
        search_code_version="conversation-state-test",
    )


def update(slot_key: str, value: str | bool | int | float | None, *, resolve_conflict: bool = False) -> ExtractedSlotUpdate:
    return ExtractedSlotUpdate(
        issue_id="q01_owner_proxy",
        slot_key=slot_key,
        status=SlotStatus.CONFIRMED,
        value=value,
        resolve_conflict=resolve_conflict,
    )


def validate_router() -> None:
    expected = {
        "집주인 아들이 대신 계약하러 왔는데 위임장 없이 계약해도 되나요?": "q01_owner_proxy",
        "공동명의 집인데 소유자 한 명만 나와서 계약해도 되나요?": "q02_co_owner",
        "등기부등본 소유자랑 계약서 임대인 이름이 다른데 괜찮나요?": "q03_owner_lessor_mismatch",
        "부동산 계좌로 계약금을 보내라고 하는데 괜찮나요?": "q04_broker_account_payment",
        "계약 직전에 계좌가 바뀌었다고 하는데 어떻게 확인해야 하나요?": "q05_account_change_before_contract",
        "중개대상물 확인설명서 내용이 계약서랑 다르면 어떻게 봐야 하나요?": "q06_broker_explanation_mismatch",
        "등기부등본에 근저당이 있는데 전세계약해도 되나요?": "q07_mortgage",
        "다가구주택인데 선순위 보증금이 많으면 위험한가요?": "q08_multiunit_priority",
        "등기부등본에 압류, 가압류 같은 권리 제한이 있으면 계약 전에 어떻게 확인해야 하나요?": "q09_registry_restriction_warning",
        "신탁등기가 있는 집인데 임대인이랑 바로 계약해도 되나요?": "q10_trust",
        "전입신고를 하면 대항력이 언제 생기나요?": "q11_opposability_move_in",
        "확정일자를 받으면 우선변제권이 생기나요?": "q12_fixed_date_priority",
        "계약 후 집주인이 바뀌었다고 하는데 제 보증금은 어떻게 되나요?": "q13_owner_change",
        "계약서 특약이나 계약금 반환 조건은 어떻게 확인해야 하나요?": "q14_special_clause_deposit_return",
        "계약서 쓴 직후에 바로 해야 할 절차가 뭐예요?": "q15_after_contract_procedure",
        "주택 임대차신고는 꼭 해야 하나요?": "q16_lease_report",
        "전입세대확인서는 언제 확인해야 하나요?": "q17_household_certificate",
        "계약서 주소와 등기부등본 주소가 조금 다른데 어떻게 봐야 하나요?": "q18_address_mismatch",
        "계약서 보증금이랑 이체 내역 금액이 다르면 어떻게 해야 하나요?": "q19_deposit_transfer_mismatch",
        "전세보증금반환보증 가입 전에 뭘 확인해야 하나요?": "q20_guarantee_check",
    }
    for question, issue_id in expected.items():
        assert route_issues(question).primary_issue_id == issue_id

    combined = route_issues("공동명의 집인데 한 명만 나왔고 부동산 계좌로 송금하라고 합니다.")
    assert combined.primary_issue_id == "q02_co_owner"
    assert "q04_broker_account_payment" in combined.related_issue_ids


def validate_store() -> None:
    store = MemoryConversationStore()
    state = create_conversation_state("q01_owner_proxy")
    created = store.create(state)
    assert store.count() == 1 and store.exists(created.conversation_id)

    loaded = store.get(created.conversation_id)
    loaded.last_risk_level = "확인 필요"
    assert store.get(created.conversation_id).last_risk_level is None
    store.save(loaded)
    assert store.get(created.conversation_id).last_risk_level == "확인 필요"

    store.reset(created.conversation_id)
    assert store.count() == 0
    try:
        store.get(created.conversation_id)
    except ConversationNotFoundError:
        pass
    else:
        raise AssertionError("삭제한 conversation_id 조회가 실패하지 않았습니다.")


def validate_state_updates() -> None:
    state = create_conversation_state("q01_owner_proxy")
    first = apply_slot_updates(
        state,
        [
            update("owner_proxy_intent_confirmed", True),
            update("payment_account_holder", "집주인"),
        ],
        strict=True,
    )
    assert first.changed_count == 2

    conflict = apply_slot_updates(state, [update("payment_account_holder", "부동산")], strict=True)
    slot = state.issue_slots["q01_owner_proxy"]["payment_account_holder"]
    assert conflict.applied[0].conflict_created is True
    assert slot.status == SlotStatus.CONFLICT
    assert set(slot.conflicting_values) == {"집주인", "부동산"}

    resolved = apply_slot_updates(
        state,
        [update("payment_account_holder", "집주인", resolve_conflict=True)],
        strict=True,
    )
    assert resolved.applied[0].conflict_resolved is True
    assert slot.status == SlotStatus.CONFIRMED and slot.value == "집주인"

    uncertain = apply_slot_updates(
        state,
        [
            ExtractedSlotUpdate(
                issue_id="q01_owner_proxy",
                slot_key="delegation_scope_confirmed",
                status=SlotStatus.UNCERTAIN,
                value=None,
            )
        ],
        strict=True,
    )
    assert uncertain.changed_count == 1


def validate_follow_up_questions() -> None:
    state = create_conversation_state("q01_owner_proxy")
    initial = build_follow_up_questions(state, max_questions=3, mark_as_asked=True)
    assert len(initial) == 3

    apply_slot_updates(
        state,
        [
            update("registered_owner_identified", "홍길동"),
            update("owner_proxy_intent_confirmed", True),
        ],
        strict=True,
    )
    after = build_follow_up_questions(state, max_questions=3, mark_as_asked=False)
    keys = {item.slot_key for item in after}
    assert "registered_owner_identified" not in keys
    assert "owner_proxy_intent_confirmed" not in keys

    apply_slot_updates(state, [update("delegation_document_available", False)], strict=True)
    missing = build_follow_up_questions(state, max_questions=7, mark_as_asked=False)
    assert any(
        item.slot_key == "delegation_document_available" and "충족되지 않았습니다" in item.question
        for item in missing
    )

    apply_slot_updates(
        state,
        [update("payment_account_holder", "집주인"), update("payment_account_holder", "부동산")],
        strict=True,
    )
    conflict = build_follow_up_questions(state, max_questions=3, mark_as_asked=False)
    assert conflict[0].slot_key == "payment_account_holder"
    assert conflict[0].status == SlotStatus.CONFLICT


def validate_conversation_service() -> None:
    store = MemoryConversationStore()
    service = APartConversationService(store=store, rag_answerer=fake_rag_answerer)

    first = service.handle(
        "집주인 아들이 대신 계약하러 왔는데 위임장 없이 계약해도 되나요?",
        issue_id="q01_owner_proxy",
        slot_updates=[update("delegation_document_available", False)],
    )
    assert first.is_new_conversation is True
    assert first.primary_issue_id == "q01_owner_proxy"
    assert len(first.follow_up_questions) <= 3

    second = service.handle(
        "집주인과 직접 통화했고 계좌도 집주인 명의예요.",
        conversation_id=first.conversation_id,
        slot_updates=[update("owner_proxy_intent_confirmed", True), update("payment_account_holder", "집주인")],
    )
    assert second.is_new_conversation is False

    third = service.handle(
        "위임장을 받았고 계약 체결·서명·계약금 수령 권한이 모두 적혀 있어요.",
        conversation_id=first.conversation_id,
        slot_updates=[
            update("registered_owner_identified", "홍길동"),
            update("delegation_document_available", True),
            update("delegation_scope_confirmed", True),
            update("signature_authority_confirmed", True),
            update("payment_authority_confirmed", True),
        ],
    )
    assert third.conflict_facts

    fourth = service.handle(
        "위임장 원본을 다시 확인했고 현재 위임장이 있는 것이 최종 확인 내용입니다.",
        conversation_id=first.conversation_id,
        slot_updates=[update("delegation_document_available", True, resolve_conflict=True)],
    )
    assert fourth.conflict_facts == []
    assert fourth.rag_response.answer.risk_level == "확인 필요"
    assert fourth.rag_response.answer.hold_actions == []

    fifth = service.handle(
        "다시 보니 계좌는 부동산 명의예요.",
        conversation_id=first.conversation_id,
        slot_updates=[update("payment_account_holder", "부동산")],
    )
    assert fifth.conflict_facts
    assert fifth.follow_up_questions[0].slot_key == "payment_account_holder"

    state = service.get_state(first.conversation_id)
    assert state.turn_count == 5
    assert len(state.messages) == 10
    service.reset(first.conversation_id)
    assert store.count() == 0


def main() -> None:
    checks = [
        ("q01~q20 질문 라우팅", validate_router),
        ("서버 메모리 저장·조회·초기화", validate_store),
        ("후속 답변 슬롯 갱신·충돌 처리", validate_state_updates),
        ("확인된 질문 제거·남은 질문 생성", validate_follow_up_questions),
        ("여러 턴 conversation service 통합", validate_conversation_service),
    ]
    for label, check in checks:
        check()
        print("PASS:", label)

    print()
    print("=" * 100)
    print("A파트 conversation state 전체 검증")
    print("-" * 100)
    print("검증 항목: 5개")
    print("conversation_id 생성: PASS")
    print("상태 저장·조회·초기화: PASS")
    print("후속 답변 슬롯 반영: PASS")
    print("확인된 질문 재출력 방지: PASS")
    print("unknown·uncertain·conflict 질문 우선순위: PASS")
    print("기존 답변과 새 답변 충돌 감지: PASS")
    print("위험 수준·보류 행동 재계산: PASS")
    print("복합 질문 primary + related issue: PASS")
    print("최종 판정: PASS")


if __name__ == "__main__":
    main()
