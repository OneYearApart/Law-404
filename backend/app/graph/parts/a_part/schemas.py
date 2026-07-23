"""A파트 LangChain·LangGraph에서 공유하는 구조화 스키마."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field, field_validator

from app.consultation.a_part.issues import get_supported_issue_ids

SUPPORTED_ISSUE_IDS = frozenset(get_supported_issue_ids())


class APartRouteDecision(BaseModel):
    """사용자 질문을 A파트 상담 이슈와 검색 문장으로 변환한 결과."""

    in_scope: bool = True
    primary_issue_id: str = "q15_after_contract_procedure"
    related_issue_ids: list[str] = Field(default_factory=list, max_length=2)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    search_query: str = ""
    reason: str = ""

    @field_validator("primary_issue_id")
    @classmethod
    def validate_primary_issue_id(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if normalized not in SUPPORTED_ISSUE_IDS:
            raise ValueError(f"지원하지 않는 A파트 issue_id입니다: {normalized}")
        return normalized

    @field_validator("related_issue_ids")
    @classmethod
    def validate_related_issue_ids(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            normalized = str(value or "").strip()
            if normalized not in SUPPORTED_ISSUE_IDS:
                continue
            if normalized not in result:
                result.append(normalized)
        return result[:2]


class APartSearchPlan(BaseModel):
    """현재 질문·문서 분석 결과를 RAG 검색에 적합한 문장으로 바꾼 결과."""

    query_override: str = Field(min_length=1, max_length=3000)
    focus_terms: list[str] = Field(default_factory=list, max_length=12)
    reason: str = ""


class APartGraphState(TypedDict, total=False):
    """한 API 턴에서 LangGraph 노드들이 주고받는 상태."""

    request: Any
    conversation_id: str
    is_new_conversation: bool
    route_decision: APartRouteDecision
    route_engine: str
    document_mode: Literal[
        "general",
        "lease_contract",
        "registry",
        "combined_documents",
    ]
    should_analyze_documents: bool
    document_analysis: Any
    rag_options: dict[str, Any]
    query_planner_engine: str
    consultation: Any
    warnings: list[str]
    result: Any
