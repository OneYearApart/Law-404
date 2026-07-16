"""첫 질문과 후속 답변을 하나의 A파트 상담 상태로 연결한다."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from app.consultation.a_part.models import (
    ConversationState,
    MessageRole,
    add_issue_to_state,
    create_conversation_state,
)
from app.consultation.a_part.question_builder import (
    FollowUpQuestion,
    build_follow_up_questions,
    confirmed_fact_sentences,
    conflict_fact_labels,
    missing_fact_labels,
)
from app.consultation.a_part.router import (
    UnsupportedConsultationIssueError,
    detect_primary_issue_id,
    route_issues,
)
from app.consultation.a_part.state_policy import (
    ConversationRiskAssessment,
    apply_state_policy_to_response,
)
from app.consultation.a_part.state_updater import (
    AppliedSlotUpdate,
    ExtractedSlotUpdate,
    OpenAISlotUpdateExtractor,
    SlotUpdateExtractor,
    apply_slot_updates,
)
from app.consultation.a_part.store import (
    DEFAULT_CONVERSATION_STORE,
    MemoryConversationStore,
    PostgresConversationStore,
)
from app.documents.models import UploadedDocument


RAGAnswerer = Callable[..., Any]


class ConversationRAGContext(BaseModel):
    """테스트용 또는 외부 RAG 함수에 전달할 최소 상담 문맥."""

    contract_stage: str = "잘 모르겠음"
    payment_status: str = "잘 모르겠음"
    contract_type: str = "잘 모르겠음"
    known_facts: list[str] = Field(default_factory=list, max_length=10)


class ConsultationTurnResponse(BaseModel):
    conversation_id: str
    is_new_conversation: bool
    primary_issue_id: str
    related_issue_ids: list[str] = Field(default_factory=list)
    applied_updates: list[AppliedSlotUpdate] = Field(default_factory=list)
    known_facts: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    conflict_facts: list[str] = Field(default_factory=list)
    follow_up_questions: list[FollowUpQuestion] = Field(default_factory=list)
    risk_assessment: ConversationRiskAssessment
    rag_response: Any
    rag_generation_status: str = "completed"
    answer_ready: bool = True
    warnings: list[str] = Field(default_factory=list)
    state: ConversationState


class APartConversationService:
    """텍스트 상담 상태와 기존 RAG 답변기를 연결하는 서비스."""

    def __init__(
        self,
        *,
        store: MemoryConversationStore | PostgresConversationStore | None = None,
        slot_extractor: SlotUpdateExtractor | None = None,
        rag_answerer: RAGAnswerer | None = None,
    ) -> None:
        self._store = store or DEFAULT_CONVERSATION_STORE
        self._slot_extractor = slot_extractor
        self._rag_answerer = rag_answerer
        self._uses_default_rag = rag_answerer is None

    @property
    def store(self) -> MemoryConversationStore | PostgresConversationStore:
        return self._store

    def _get_slot_extractor(self) -> SlotUpdateExtractor:
        if self._slot_extractor is None:
            self._slot_extractor = OpenAISlotUpdateExtractor()
        return self._slot_extractor

    def _get_rag_answerer(self) -> RAGAnswerer:
        if self._rag_answerer is None:
            from app.llm.a_part import answer_with_rag_guarded
            self._rag_answerer = answer_with_rag_guarded
        return self._rag_answerer

    def _build_rag_context(self, known_facts: list[str]) -> Any:
        if self._uses_default_rag:
            from app.llm.a_part import ConsultationContext
            return ConsultationContext(known_facts=known_facts)
        return ConversationRAGContext(known_facts=known_facts)

    @staticmethod
    def _normalize_updates(
        updates: list[ExtractedSlotUpdate | dict[str, Any]] | None,
    ) -> list[ExtractedSlotUpdate] | None:
        if updates is None:
            return None
        return [
            item
            if isinstance(item, ExtractedSlotUpdate)
            else ExtractedSlotUpdate.model_validate(item)
            for item in updates
        ]

    def _extract_updates(
        self,
        *,
        question: str,
        state: ConversationState,
        explicit_updates: list[ExtractedSlotUpdate] | None,
        warnings: list[str],
    ) -> list[ExtractedSlotUpdate]:
        if explicit_updates is not None:
            return explicit_updates

        try:
            result = self._get_slot_extractor().extract(
                user_text=question,
                state=state,
            )
        except Exception as error:
            warnings.append(
                "후속 답변의 슬롯을 자동 분석하지 못했습니다. "
                f"RAG 답변은 계속 생성하지만 상태는 갱신되지 않습니다: {error}"
            )
            return []

        if result.unparsed_text:
            warnings.append(
                "일부 문장을 현재 슬롯에 연결하지 못했습니다: "
                f"{result.unparsed_text}"
            )
        return result.updates

    @staticmethod
    def _assistant_message(
        response: Any,
        follow_up_questions: list[FollowUpQuestion],
    ) -> str:
        parts = [str(response.answer.core_judgment)]
        if follow_up_questions:
            parts.append("추가 확인 질문")
            parts.extend(
                f"{index}. {item.question}"
                for index, item in enumerate(
                    follow_up_questions,
                    start=1,
                )
            )
        return "\n".join(parts)

    @staticmethod
    def _try_add_new_issue(
        state: ConversationState,
        *,
        question: str,
        explicit_issue_id: str | None,
    ) -> bool:
        candidate: str | None = explicit_issue_id

        if candidate is None:
            try:
                candidate = detect_primary_issue_id(question)
            except UnsupportedConsultationIssueError:
                candidate = None

        if not candidate or candidate in state.all_issue_ids:
            return False

        add_issue_to_state(state, candidate, as_related=True)
        return True

    def handle(
        self,
        question: str,
        *,
        conversation_id: str | None = None,
        issue_id: str | None = None,
        related_issue_ids: list[str] | None = None,
        slot_updates: list[ExtractedSlotUpdate | dict[str, Any]] | None = None,
        rag_options: dict[str, Any] | None = None,
    ) -> ConsultationTurnResponse:
        """새 상담을 만들거나 기존 상담에 후속 답변을 반영한다."""

        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("question은 빈 문자열일 수 없습니다.")

        warnings: list[str] = []
        normalized_rag_options = dict(rag_options or {})
        apply_state_policy = bool(
            normalized_rag_options.pop("apply_state_policy", True)
        )
        build_follow_ups = bool(
            normalized_rag_options.pop("build_follow_up_questions", True)
        )
        suppress_no_update_warning = bool(
            normalized_rag_options.pop("suppress_no_update_warning", False)
        )
        explicit_updates = self._normalize_updates(slot_updates)
        is_new = conversation_id is None
        new_issue_added = False

        if is_new:
            routed = route_issues(
                normalized_question,
                primary_issue_id=issue_id,
                related_issue_ids=related_issue_ids,
            )
            state = create_conversation_state(
                primary_issue_id=routed.primary_issue_id,
                related_issue_ids=list(routed.related_issue_ids),
            )
        else:
            state = self._store.get(conversation_id)
            new_issue_added = self._try_add_new_issue(
                state,
                question=normalized_question,
                explicit_issue_id=issue_id,
            )
            for related_id in related_issue_ids or []:
                if related_id not in state.all_issue_ids:
                    add_issue_to_state(state, related_id, as_related=True)
                    new_issue_added = True

        state.append_message(MessageRole.USER, normalized_question)

        extracted_updates = self._extract_updates(
            question=normalized_question,
            state=state,
            explicit_updates=explicit_updates,
            warnings=warnings,
        )
        update_summary = apply_slot_updates(state, extracted_updates)
        warnings.extend(update_summary.ignored)

        if (
            not suppress_no_update_warning
            and not is_new
            and not new_issue_added
            and not update_summary.applied
        ):
            warnings.append(
                "이번 후속 답변에서 새로 확인된 슬롯을 찾지 못했습니다. "
                "남은 질문에 맞춰 사실을 조금 더 구체적으로 답해 주세요."
            )

        known_facts = confirmed_fact_sentences(state, max_items=10)
        consultation_context = self._build_rag_context(known_facts)

        # 짧은 후속 답변 자체로 검색하면 근거가 빗나갈 수 있으므로,
        # 기존 issue에 대한 답이면 첫 질문을 검색어로 유지한다.
        rag_query = normalized_question
        if not is_new and not new_issue_added:
            rag_query = state.initial_query or normalized_question

        query_override = str(
            normalized_rag_options.pop("query_override", "") or ""
        ).strip()
        if query_override:
            rag_query = query_override

        response = self._get_rag_answerer()(
            query=rag_query,
            consultation_context=consultation_context,
            **normalized_rag_options,
        )

        follow_up_questions = (
            build_follow_up_questions(
                state,
                max_questions=3,
                mark_as_asked=True,
            )
            if build_follow_ups
            else []
        )
        if apply_state_policy:
            response, assessment = apply_state_policy_to_response(
                response,
                state=state,
                follow_up_questions=follow_up_questions,
            )
        else:
            assessment = ConversationRiskAssessment(
                risk_level=response.answer.risk_level,
                core_judgment=response.answer.core_judgment,
                hold_actions=list(response.answer.hold_actions),
            )

        state.last_risk_level = response.answer.risk_level
        state.last_answer = response.model_dump(mode="json")
        state.append_message(
            MessageRole.ASSISTANT,
            self._assistant_message(response, follow_up_questions),
        )

        stored = self._store.create(state) if is_new else self._store.save(state)

        generation_status = getattr(response, "generation_status", "completed")
        generation_value = getattr(generation_status, "value", generation_status)
        answer_ready = generation_value in {"completed", "partial_evidence"}
        return ConsultationTurnResponse(
            conversation_id=stored.conversation_id,
            is_new_conversation=is_new,
            primary_issue_id=stored.primary_issue_id,
            related_issue_ids=list(stored.related_issue_ids),
            applied_updates=update_summary.applied,
            known_facts=confirmed_fact_sentences(stored, max_items=10),
            missing_facts=missing_fact_labels(stored),
            conflict_facts=conflict_fact_labels(stored),
            follow_up_questions=follow_up_questions,
            risk_assessment=assessment,
            rag_response=response,
            rag_generation_status=str(generation_value),
            answer_ready=answer_ready,
            warnings=[*warnings, *(getattr(response, "warnings", []) or [])],
            state=stored,
        )

    def get_state(self, conversation_id: str) -> ConversationState:
        return self._store.get(conversation_id)

    def attach_document(
        self,
        conversation_id: str,
        document: UploadedDocument,
    ) -> ConversationState:
        state = self._store.get(conversation_id)
        state.attach_document(document)
        return self._store.save(state)

    def update_document(
        self,
        conversation_id: str,
        document: UploadedDocument,
    ) -> ConversationState:
        state = self._store.get(conversation_id)
        state.update_document(document)
        return self._store.save(state)

    def reset(self, conversation_id: str) -> ConversationState:
        return self._store.reset(conversation_id)

    def delete(self, conversation_id: str) -> bool:
        return self._store.delete(conversation_id)


DEFAULT_CONVERSATION_SERVICE = APartConversationService()


def handle_consultation(
    question: str,
    *,
    conversation_id: str | None = None,
    issue_id: str | None = None,
    related_issue_ids: list[str] | None = None,
    slot_updates: list[ExtractedSlotUpdate | dict[str, Any]] | None = None,
    rag_options: dict[str, Any] | None = None,
) -> ConsultationTurnResponse:
    return DEFAULT_CONVERSATION_SERVICE.handle(
        question,
        conversation_id=conversation_id,
        issue_id=issue_id,
        related_issue_ids=related_issue_ids,
        slot_updates=slot_updates,
        rag_options=rag_options,
    )


def get_conversation_state(conversation_id: str) -> ConversationState:
    return DEFAULT_CONVERSATION_SERVICE.get_state(conversation_id)


def update_conversation_document(
    conversation_id: str,
    document: UploadedDocument,
) -> ConversationState:
    return DEFAULT_CONVERSATION_SERVICE.update_document(
        conversation_id,
        document,
    )


def reset_conversation(conversation_id: str) -> ConversationState:
    return DEFAULT_CONVERSATION_SERVICE.reset(conversation_id)


def attach_document_to_conversation(
    conversation_id: str,
    document: UploadedDocument,
) -> ConversationState:
    return DEFAULT_CONVERSATION_SERVICE.attach_document(
        conversation_id,
        document,
    )
