"""질문·체크리스트·문서·상태·RAG를 한 번에 처리하는 A파트 내부 챗봇 서비스."""

from __future__ import annotations

from enum import Enum
import re
from typing import Any

from pydantic import BaseModel, Field

from backend.app.consultation.a_part.document_service import (
    APartDocumentUploadService,
)
from backend.app.consultation.a_part.models import (
    MessageRole,
    add_issue_to_state,
    create_conversation_state,
)
from backend.app.consultation.a_part.router import route_issues
from backend.app.consultation.a_part.service import (
    APartConversationService,
    ConsultationTurnResponse,
)
from backend.app.consultation.a_part.state_updater import ExtractedSlotUpdate
from backend.app.documents.analysis.models import (
    ComparisonStatus,
    ConversationDocumentAnalysisResponse,
)
from backend.app.documents.analysis.normalization import repair_address_ocr



def _analysis_field(analysis: Any, key: str) -> Any | None:
    return getattr(analysis, "fields", {}).get(key)


def _analysis_field_value(analysis: Any, key: str) -> Any | None:
    field = _analysis_field(analysis, key)
    return None if field is None else field.value


def _analysis_field_status(analysis: Any, key: str) -> str:
    field = _analysis_field(analysis, key)
    status = getattr(field, "status", None)
    return str(getattr(status, "value", status) or "unknown")


def _short_text(value: Any, *, max_chars: int = 180) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def _format_money(value: Any | None) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return f"{int(value):,}원"


def _clean_address(value: Any | None) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = repair_address_ocr(value)
    return normalized or " ".join(value.split())


def _unique_text(items: list[str], *, max_items: int) -> list[str]:
    result: list[str] = []
    for item in items:
        normalized = " ".join(str(item or "").split()).strip()
        if normalized and normalized not in result:
            result.append(normalized)
        if len(result) >= max_items:
            break
    return result


def _compact_korean(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip()
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"(?<=[가-힣])\s+(?=[가-힣])", "", text)
    return text


def _summarize_special_clause(value: Any) -> str | None:
    cleaned = _compact_korean(value)
    compact = re.sub(r"[^0-9가-힣]", "", cleaned)
    rules = [
        (("현시설물", "등기사항증명서"), "현 시설 상태와 등기사항증명서·현장 확인을 전제로 계약합니다."),
        (("근저당권설정", "권리관계"), "계약 당시 근저당권 설정이 없고 임차 기간 중 권리관계 변동을 두지 않기로 정했습니다."),
        (("전입신고", "확정일자"), "임차인의 전입신고와 확정일자 부여를 허용합니다."),
        (("전세권설정", "말소"), "임대인은 전세권 설정에 협조하고 설정·말소 비용은 임차인이 부담하며, 보증금 반환과 말소를 동시 이행하도록 정했습니다."),
        (("반려동물", "실내흡연"), "반려동물 사육과 실내 흡연을 금지합니다."),
        (("계약기간중퇴거", "중개보수"), "임차인이 계약기간 중 퇴거하면 다음 임차인 모집 중개보수를 부담하도록 정했습니다."),
        (("원상복구", "하자보수"), "임차인 과실로 시설물이 훼손되면 원상복구하고 하자보수에 협조하도록 정했습니다."),
        (("체크리스트", "퇴거"), "입주 시 체크리스트를 작성하고 퇴거 시 이상 없이 인도하도록 정했습니다."),
        (("주택임대차보호법",), "기타 사항은 주택임대차보호법과 일반 관례를 따르도록 정했습니다."),
    ]
    for keywords, summary in rules:
        if all(keyword in compact for keyword in keywords):
            return summary

    cleaned = re.sub(r"\b[A-Za-z]{2,}\b", "", cleaned)
    cleaned = " ".join(cleaned.split()).strip(" -|,.;:")
    return _short_text(cleaned, max_chars=140) if len(cleaned) >= 8 else None


def _is_user_facing_warning(value: Any) -> bool:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return False
    internal_markers = (
        "페이지 순서대로 병합",
        "직접 추출 결과가 부족",
        "PSM ",
        "Tesseract",
        "텍스트 레이어",
        "공백 제외 글자 수",
    )
    return not any(marker in text for marker in internal_markers)


class ChatbotProcessingStatus(str, Enum):
    COMPLETED = "completed"
    NEEDS_FOLLOW_UP = "needs_follow_up"
    PARTIAL_EVIDENCE = "partial_evidence"
    RAG_EVIDENCE_NOT_FOUND = "rag_evidence_not_found"
    RAG_SEARCH_FAILED = "rag_search_failed"
    RAG_GENERATION_FAILED = "rag_generation_failed"
    RAG_VALIDATION_FAILED = "rag_validation_failed"


class ChatbotTurnRequest(BaseModel):
    question: str = Field(min_length=1)
    conversation_id: str | None = None
    issue_id: str | None = None
    related_issue_ids: list[str] = Field(default_factory=list)
    checklist_updates: list[ExtractedSlotUpdate | dict[str, Any]] = Field(
        default_factory=list
    )
    document_ids: list[str] = Field(default_factory=list)
    analyze_documents: bool = True
    force_document_analysis: bool = False
    rag_options: dict[str, Any] = Field(default_factory=dict)


class ChatbotTurnResult(BaseModel):
    conversation_id: str
    processing_status: ChatbotProcessingStatus
    answer_ready: bool
    is_new_conversation: bool
    document_analysis: ConversationDocumentAnalysisResponse | None = None
    consultation: ConsultationTurnResponse
    warnings: list[str] = Field(default_factory=list)


class APartChatbotService:
    """FastAPI와 분리된 챗봇 내부 처리 흐름이다."""

    def __init__(
        self,
        *,
        conversation_service: APartConversationService | None = None,
        document_service: APartDocumentUploadService | None = None,
    ) -> None:
        self.conversation_service = (
            conversation_service or APartConversationService()
        )
        self.document_service = document_service or APartDocumentUploadService(
            conversation_service=self.conversation_service
        )

    def _ensure_conversation(
        self, request: ChatbotTurnRequest
    ) -> tuple[str, bool]:
        if request.conversation_id:
            state = self.conversation_service.get_state(
                request.conversation_id
            )
            routed = route_issues(
                request.question,
                primary_issue_id=request.issue_id,
                related_issue_ids=request.related_issue_ids,
            )
            changed = False
            for issue_id in (
                routed.primary_issue_id,
                *routed.related_issue_ids,
            ):
                if issue_id in state.all_issue_ids:
                    continue
                add_issue_to_state(
                    state,
                    issue_id,
                    as_related=True,
                )
                changed = True
            if changed:
                self.conversation_service.store.save(state)
            return request.conversation_id, False

        routed = route_issues(
            request.question,
            primary_issue_id=request.issue_id,
            related_issue_ids=request.related_issue_ids,
        )
        state = create_conversation_state(
            primary_issue_id=routed.primary_issue_id,
            related_issue_ids=list(routed.related_issue_ids),
        )
        stored = self.conversation_service.store.create(state)
        return stored.conversation_id, True

    @staticmethod
    def _document_rag_query(
        *,
        user_question: str,
        document_analysis: ConversationDocumentAnalysisResponse | None,
    ) -> str | None:
        """문서에서 실제로 확인된 위험만 RAG 검색어에 반영한다.

        `근저당 없음`, `신탁 없음`처럼 부정된 위험 키워드를 검색문에 넣지
        않는다. 현재 활성 위험이 없으면 계약 직후 보호 절차와 최신 등기부
        재확인 근거를 검색한다.
        """
        if document_analysis is None:
            return None

        facts: list[str] = []
        topics: list[str] = [
            "계약서 핵심 내용 확인",
            "계약서 원본과 지급 증빙 보관",
            "잔금 직전 최신 등기부등본 재확인",
            "전입신고",
            "확정일자",
            "주택 임대차신고",
            "보증금 보호 절차",
        ]
        active_risk_topics: list[str] = []
        registry_uncertain = False

        if document_analysis.lease_analyses:
            lease = document_analysis.lease_analyses[-1]
            values = []
            for key, label, formatter in (
                ("lessor_name", "임대인", None),
                ("lessee_name", "임차인", None),
                ("property_address", "목적물", _clean_address),
                ("deposit_amount", "보증금", _format_money),
                ("contract_date", "계약일", None),
                ("contract_start_date", "계약 시작일", None),
                ("contract_end_date", "계약 종료일", None),
            ):
                value = _analysis_field_value(lease, key)
                value = formatter(value) if formatter else value
                if value not in (None, "", []):
                    values.append(f"{label} {value}")
            if values:
                facts.append("계약서에서 확인된 내용: " + ", ".join(values))
            if lease.special_clauses:
                topics.append("임대차계약 특약 확인")

        if document_analysis.registry_analyses:
            registry = document_analysis.registry_analyses[-1]
            owners = _analysis_field_value(registry, "current_owners")
            owner_text = (
                ", ".join(str(item) for item in owners if item)
                if isinstance(owners, list)
                else str(owners or "").strip()
            )
            if owner_text:
                facts.append(f"등기부 현재 소유자 {owner_text}")

            risk_fields = (
                ("mortgage_exists", "근저당", ["근저당", "채권최고액", "선순위 권리", "계약·송금 보류 기준"]),
                ("active_restriction_exists", "압류·가압류 등 권리 제한", ["압류", "가압류", "말소 여부", "계약·송금 보류 기준"]),
                ("trust_registration_exists", "신탁등기", ["신탁원부", "수탁자", "임대 권한", "수탁자 동의"]),
            )
            for key, label, risk_topics in risk_fields:
                value = _analysis_field_value(registry, key)
                status = _analysis_field_status(registry, key)
                if value is True:
                    facts.append(f"현재 유효한 {label} 확인")
                    active_risk_topics.extend(risk_topics)
                elif value is None or status not in {"confirmed", "uncertain"}:
                    registry_uncertain = True

            if not active_risk_topics:
                topics.extend(
                    [
                        "등기부 현재 소유자 확인",
                        "현재 권리관계 확인 결과의 의미",
                    ]
                )
            if registry_uncertain:
                topics.append("등기부 OCR 판독 불확실 항목 원본 재확인")

        comparison = document_analysis.comparison
        if comparison is not None:
            for item in comparison.comparisons:
                status = str(getattr(item.status, "value", item.status))
                if status == ComparisonStatus.MATCH.value:
                    if item.key == "owner_lessor":
                        facts.append("계약서 임대인과 등기부 현재 소유자 일치")
                    elif item.key == "property_address":
                        facts.append("계약서와 등기부 목적물 주소 일치")
                elif status == ComparisonStatus.MISMATCH.value:
                    facts.append("문서 불일치: " + _short_text(item.explanation, max_chars=120))
                    active_risk_topics.append("문서 불일치 확인 및 정정 전 계약·송금 보류")
                elif status not in {ComparisonStatus.NOT_APPLICABLE.value}:
                    topics.append("계약서와 등기부 대조 불확실 항목 원본 확인")

        if not facts and not topics:
            return None

        requested = " ".join(user_question.split()).strip()
        search_topics = _unique_text([*active_risk_topics, *topics], max_items=14)
        return (
            f"사용자 요청: {requested}. "
            + (" ".join(facts) + ". " if facts else "")
            + "공식 법령·판례·절차 자료를 근거로 설명할 내용: "
            + ", ".join(search_topics)
            + ". 문서에 없는 사실은 단정하지 않고 OCR 불확실 항목은 원본 재확인을 안내한다."
        )

    @staticmethod
    def _document_answer_summary(
        document_analysis: ConversationDocumentAnalysisResponse,
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        sections: list[dict[str, Any]] = []
        warnings: list[str] = []
        reasons: list[str] = []
        follow_up_questions: list[str] = []
        source_ids: set[str] = set()

        if document_analysis.lease_analyses:
            lease = document_analysis.lease_analyses[-1]
            source_ids.update(lease.source_document_ids or [lease.document_id])

            def lease_item(
                key: str,
                label: str,
                formatter=None,
                *,
                required: bool = True,
            ) -> str | None:
                field = _analysis_field(lease, key)
                value = None if field is None else field.value
                status = _analysis_field_status(lease, key)
                if formatter is not None:
                    value = formatter(value)
                if value not in (None, "", []):
                    suffix = "" if status == "confirmed" else f" ({status})"
                    return f"{label}: {value}{suffix}"
                if not required:
                    return None
                warning = f"계약서에서 {label}을 확인하지 못했습니다."
                warnings.append(warning)
                follow_up_questions.append(
                    f"계약서 원본에서 {label}을 직접 확인해 주시겠어요?"
                )
                return f"{label}: 확인 필요"

            contract_items = [
                lease_item("lessor_name", "임대인"),
                lease_item("lessee_name", "임차인"),
                lease_item("property_address", "목적물 주소", _clean_address),
            ]
            money_items = [
                item
                for item in [
                    lease_item("deposit_amount", "보증금", _format_money),
                    lease_item("contract_payment", "계약금", _format_money),
                    lease_item("interim_payment", "중도금", _format_money, required=False),
                    lease_item("balance_payment", "잔금", _format_money),
                    lease_item("monthly_rent", "월세", _format_money, required=False),
                    lease_item("maintenance_fee", "관리비", _format_money, required=False),
                ]
                if item is not None
            ]
            date_items = [
                lease_item("contract_date", "계약일"),
                lease_item("move_in_date", "입주일"),
                lease_item("contract_start_date", "계약 시작일"),
                lease_item("contract_end_date", "계약 종료일"),
            ]
            sections.extend(
                [
                    {"title": "계약 당사자·목적물", "items": contract_items},
                    {"title": "금액", "items": money_items},
                    {"title": "일정", "items": date_items},
                ]
            )

            clause_items: list[str] = []
            for clause in lease.special_clauses[:12]:
                summary_text = _summarize_special_clause(clause.text)
                if summary_text and summary_text not in clause_items:
                    clause_items.append(summary_text)
                if len(clause_items) >= 9:
                    break
            if clause_items:
                sections.append({"title": "주요 특약", "items": clause_items})
            else:
                warnings.append("계약서에서 특약 문구를 확인하지 못했습니다.")
            warnings.extend(
                _short_text(item)
                for item in lease.warnings
                if _is_user_facing_warning(item)
            )
            reasons.append("계약서의 당사자·목적물·금액·일정·특약을 항목별로 분석했습니다.")

        if document_analysis.registry_analyses:
            registry = document_analysis.registry_analyses[-1]
            source_ids.update(registry.source_document_ids or [registry.document_id])
            owners = _analysis_field_value(registry, "current_owners")
            owner_text = (
                ", ".join(str(item) for item in owners if item)
                if isinstance(owners, list)
                else str(owners or "").strip()
            )

            def registry_bool(key: str, label: str) -> str:
                value = _analysis_field_value(registry, key)
                status = _analysis_field_status(registry, key)
                if value is True:
                    return f"{label}: 있음" + ("" if status == "confirmed" else f" ({status})")
                if value is False:
                    return f"{label}: 현재 유효한 기록 확인되지 않음" + ("" if status == "confirmed" else f" ({status})")
                warnings.append(f"등기부의 {label} 여부를 확정하지 못했습니다.")
                follow_up_questions.append(
                    f"최신 등기부 원본에서 {label} 여부를 다시 확인해 주시겠어요?"
                )
                return f"{label}: 확인 필요"

            registry_items = [
                f"등기 목적물: {_clean_address(_analysis_field_value(registry, 'registry_address')) or '확인 필요'}",
                f"현재 소유자: {owner_text or '확인 필요'}",
                registry_bool("mortgage_exists", "근저당"),
                registry_bool("active_restriction_exists", "압류·가압류 등 권리 제한"),
                registry_bool("trust_registration_exists", "신탁등기"),
            ]
            cancelled_trusts = [
                item for item in registry.trusts if item.active is False
            ]
            if cancelled_trusts:
                registry_items.append(
                    f"말소된 과거 신탁 기록: {len(cancelled_trusts)}건"
                )
            sections.append({"title": "등기부 현재 권리관계", "items": registry_items})
            warnings.extend(
                _short_text(item)
                for item in registry.warnings
                if _is_user_facing_warning(item)
            )
            reasons.append("등기부의 현재 유효한 권리와 말소된 과거 기록을 구분했습니다.")

        comparison = document_analysis.comparison
        if comparison is not None:
            comparison_items = []
            for item in comparison.comparisons:
                status = str(getattr(item.status, "value", item.status))
                comparison_items.append(
                    f"{item.key}: {status} - {_short_text(item.explanation)}"
                )
                if status in {"mismatch", "uncertain", "conflict"}:
                    warnings.append(_short_text(item.explanation))
            if comparison_items:
                sections.append({"title": "계약서·등기부 대조", "items": comparison_items})
                reasons.append("계약서와 등기부의 소유자·주소·권리관계를 대조했습니다.")

        warnings.extend(
            _short_text(item)
            for item in document_analysis.warnings
            if _is_user_facing_warning(item)
        )
        summary = {
            "source_count": len(source_ids),
            "sections": sections,
            "warnings": _unique_text(warnings, max_items=8),
        }
        return (
            summary,
            _unique_text(reasons, max_items=4),
            _unique_text(follow_up_questions, max_items=3),
        )

    @staticmethod
    def _document_risk_level(
        document_analysis: ConversationDocumentAnalysisResponse,
    ) -> tuple[str, list[str]]:
        hold_reasons: list[str] = []
        uncertain = False

        if document_analysis.lease_analyses:
            lease = document_analysis.lease_analyses[-1]
            for key in (
                "lessor_name",
                "lessee_name",
                "property_address",
                "deposit_amount",
                "contract_date",
                "contract_start_date",
                "contract_end_date",
            ):
                if _analysis_field_status(lease, key) != "confirmed":
                    uncertain = True

        if document_analysis.registry_analyses:
            registry = document_analysis.registry_analyses[-1]
            for key, label in (
                ("mortgage_exists", "현재 근저당"),
                ("active_restriction_exists", "현재 권리 제한"),
                ("trust_registration_exists", "현재 신탁등기"),
            ):
                value = _analysis_field_value(registry, key)
                status = _analysis_field_status(registry, key)
                if value is True:
                    hold_reasons.append(label)
                elif status != "confirmed":
                    uncertain = True
            if _analysis_field_status(registry, "current_owners") != "confirmed":
                uncertain = True

        comparison = document_analysis.comparison
        if comparison is not None:
            for item in comparison.comparisons:
                status = str(getattr(item.status, "value", item.status))
                if status == "mismatch":
                    hold_reasons.append(item.explanation)
                elif status not in {"match", "not_applicable"}:
                    uncertain = True

        if hold_reasons:
            return "진행 보류 권장", _unique_text(hold_reasons, max_items=3)
        if uncertain:
            return "확인 필요", []
        return "현재 입력 기준 중대한 보류 사유 미확인", []

    def _apply_document_summary(
        self,
        consultation: ConsultationTurnResponse,
        document_analysis: ConversationDocumentAnalysisResponse | None,
    ) -> ConsultationTurnResponse:
        if document_analysis is None:
            return consultation

        summary, document_reasons, document_questions = self._document_answer_summary(
            document_analysis
        )
        risk_level, hold_reasons = self._document_risk_level(document_analysis)

        rag_response = consultation.rag_response
        data = rag_response.model_dump(mode="python")
        answer = data.get("answer") or {}
        answer["document_summary"] = summary
        answer["risk_level"] = risk_level

        if hold_reasons:
            answer["core_judgment"] = (
                "첨부 문서에서 계약 진행 전에 확인해야 할 위험 요소가 발견됐습니다: "
                + "; ".join(hold_reasons)
                + ". 원본 확인과 해소 전에는 계약 또는 지급을 보류해야 합니다."
            )
            answer["hold_actions"] = _unique_text(
                [
                    "확인되지 않은 권리관계가 해소되기 전 계약 진행",
                    "확인되지 않은 권리관계가 해소되기 전 계약금 또는 잔금 지급",
                ],
                max_items=3,
            )
        elif risk_level == "확인 필요":
            answer["core_judgment"] = (
                "첨부 문서의 주요 내용은 분석했지만 OCR 또는 문서 상태 때문에 "
                "직접 재확인해야 할 항목이 남아 있습니다. 확인되지 않은 값은 "
                "원본 문서와 최신 발급 문서로 확인한 뒤 다음 절차를 진행해야 합니다."
            )
            answer["hold_actions"] = []
        else:
            answer["core_judgment"] = (
                "첨부 문서 기준으로 계약 당사자·목적물과 현재 권리관계에서 "
                "중대한 불일치는 확인되지 않았습니다. 다만 잔금 직전 최신 "
                "등기부 재확인과 전입신고·확정일자·임대차신고 등 보증금 보호 "
                "절차는 별도로 완료해야 합니다."
            )
            answer["hold_actions"] = []

        document_actions = [
            "OCR로 읽은 계약 당사자·주소·금액·날짜를 원본 문서와 한 번 더 대조합니다.",
            "계약서 원본과 계약금·잔금 이체 내역 또는 영수증을 함께 보관합니다.",
        ]
        if document_analysis.registry_analyses:
            document_actions.append(
                "잔금 또는 추가 지급 직전에 최신 등기부등본을 다시 발급해 권리 변동을 확인합니다."
            )
        else:
            document_actions.append(
                "잔금 전 최신 등기부등본을 첨부해 소유자·주소·현재 권리관계를 계약서와 대조합니다."
            )
        answer["immediate_actions"] = _unique_text(document_actions, max_items=3)
        answer["reasons"] = _unique_text(
            [*document_reasons, *(answer.get("reasons") or [])],
            max_items=4,
        )
        answer["required_information"] = _unique_text(
            [
                *summary.get("warnings", []),
                *(answer.get("required_information") or []),
            ],
            max_items=6,
        )
        answer["follow_up_questions"] = document_questions
        data["answer"] = answer

        # 계약서·등기부 분석 결과가 있으면 법률 RAG가 일시적으로 비어도
        # 문서에서 직접 확인된 사실과 비교 결과는 사용자에게 반환한다.
        # 다만 법률 근거가 완전한 답변처럼 보이지 않도록 partial_evidence로
        # 명확하게 낮춰 표시한다.
        original_generation_status = str(
            getattr(
                getattr(rag_response, "generation_status", None),
                "value",
                getattr(rag_response, "generation_status", "completed"),
            )
        )
        document_only_statuses = {
            "evidence_not_found",
            "search_failed",
            "generation_failed",
            "validation_failed",
        }
        if original_generation_status in document_only_statuses:
            data["generation_status"] = "partial_evidence"
            data["evidence_status"] = "partial"
            data["warnings"] = _unique_text(
                [
                    *(data.get("warnings") or []),
                    "문서 분석 결과는 확인했지만 법률 RAG 근거는 일부 부족합니다.",
                ],
                max_items=8,
            )

        updated_rag = rag_response.__class__.model_validate(data)

        state = consultation.state.model_copy(deep=True)
        state.last_risk_level = updated_rag.answer.risk_level
        state.last_answer = updated_rag.model_dump(mode="json")
        if state.messages and state.messages[-1].role == MessageRole.ASSISTANT:
            state.messages[-1].content = self.conversation_service._assistant_message(
                updated_rag,
                [],
            )
            state.touch()
        stored_state = self.conversation_service.store.save(state)

        assessment = consultation.risk_assessment.model_copy(
            update={
                "risk_level": updated_rag.answer.risk_level,
                "core_judgment": updated_rag.answer.core_judgment,
                "hold_actions": list(updated_rag.answer.hold_actions),
                "unresolved_critical_labels": list(summary.get("warnings", []))[:6],
                "conflict_labels": hold_reasons,
            }
        )
        return consultation.model_copy(
            update={
                "rag_response": updated_rag,
                "state": stored_state,
                "risk_assessment": assessment,
                "follow_up_questions": [],
                "missing_facts": list(summary.get("warnings", []))[:6],
                "conflict_facts": hold_reasons,
                "rag_generation_status": str(
                    getattr(
                        updated_rag.generation_status,
                        "value",
                        updated_rag.generation_status,
                    )
                ),
                "answer_ready": True,
            }
        )

    @staticmethod
    def _processing_status(
        consultation: ConsultationTurnResponse,
    ) -> ChatbotProcessingStatus:
        rag_status = consultation.rag_generation_status
        mapping = {
            "evidence_not_found": ChatbotProcessingStatus.RAG_EVIDENCE_NOT_FOUND,
            "search_failed": ChatbotProcessingStatus.RAG_SEARCH_FAILED,
            "generation_failed": ChatbotProcessingStatus.RAG_GENERATION_FAILED,
            "validation_failed": ChatbotProcessingStatus.RAG_VALIDATION_FAILED,
            "partial_evidence": ChatbotProcessingStatus.PARTIAL_EVIDENCE,
        }
        if rag_status in mapping:
            return mapping[rag_status]
        if consultation.follow_up_questions:
            return ChatbotProcessingStatus.NEEDS_FOLLOW_UP
        return ChatbotProcessingStatus.COMPLETED

    def handle(self, request: ChatbotTurnRequest) -> ChatbotTurnResult:
        conversation_id, is_new = self._ensure_conversation(request)
        warnings: list[str] = []
        document_analysis: ConversationDocumentAnalysisResponse | None = None

        state = self.conversation_service.get_state(conversation_id)
        if request.analyze_documents and (state.documents or request.document_ids):
            document_analysis = self.document_service.analyze_documents(
                conversation_id=conversation_id,
                document_ids=(request.document_ids or None),
                force=request.force_document_analysis,
            )
            warnings.extend(document_analysis.warnings)
        elif request.document_ids:
            warnings.append(
                "document_ids가 전달됐지만 analyze_documents가 false라 문서 분석을 건너뛰었습니다."
            )

        rag_options = dict(request.rag_options)
        if "query_override" not in rag_options:
            current_state = self.conversation_service.get_state(conversation_id)
            query_override = self._document_rag_query(
                user_question=request.question,
                document_analysis=document_analysis,
            )
            if query_override:
                rag_options["query_override"] = query_override

        if document_analysis is not None:
            rag_options["apply_state_policy"] = False
            rag_options["build_follow_up_questions"] = False
            rag_options["suppress_no_update_warning"] = True

        consultation = self.conversation_service.handle(
            request.question,
            conversation_id=conversation_id,
            issue_id=request.issue_id,
            related_issue_ids=request.related_issue_ids,
            slot_updates=request.checklist_updates or None,
            rag_options=rag_options,
        )
        consultation = self._apply_document_summary(
            consultation,
            document_analysis,
        )
        consultation = consultation.model_copy(
            update={"is_new_conversation": is_new}
        )
        status = self._processing_status(consultation)
        return ChatbotTurnResult(
            conversation_id=conversation_id,
            processing_status=status,
            answer_ready=consultation.answer_ready,
            is_new_conversation=is_new,
            document_analysis=document_analysis,
            consultation=consultation,
            warnings=[*warnings, *consultation.warnings],
        )
