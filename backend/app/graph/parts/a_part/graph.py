"""A파트 LangGraph 상담 오케스트레이션.

기존 RAG·문서 분석·상태 정책은 재사용하고, 한 턴의 실행 순서와 조건 분기를
LangGraph가 관리한다.
"""

from __future__ import annotations

from typing import Any

from app.consultation.a_part.input_validation import requests_document_review
from app.consultation.a_part.question_builder import confirmed_fact_sentences
from app.consultation.a_part.router import UnsupportedConsultationIssueError
from app.documents.models import DocumentType
from app.graph.parts.a_part.chains import (
    plan_search_query,
    route_question,
    should_preserve_active_issue,
)
from app.graph.parts.a_part.schemas import APartGraphState, APartRouteDecision

GRAPH_VERSION = "a-part-langgraph-v1"


def _use_langchain(service: Any) -> bool:
    """테스트용 가짜 RAG가 주입된 경우 외부 모델 호출을 피한다."""

    return bool(getattr(service.conversation_service, "_uses_default_rag", True))


def _route_node(service: Any):
    def node(state: APartGraphState) -> dict[str, Any]:
        request = state["request"]
        existing_state = None
        if request.conversation_id:
            existing_state = service.conversation_service.get_state(
                request.conversation_id
            )

        if (
            existing_state is not None
            and not request.issue_id
            and should_preserve_active_issue(request.question, existing_state)
        ):
            decision = APartRouteDecision(
                in_scope=True,
                primary_issue_id=existing_state.primary_issue_id,
                related_issue_ids=list(existing_state.related_issue_ids)[:2],
                confidence=1.0,
                search_query=existing_state.initial_query or request.question,
                reason="진행 중인 추가 질문에 대한 짧은 답변이므로 기존 이슈를 유지합니다.",
            )
            engine = "active_issue"
        else:
            decision, engine = route_question(
                request.question,
                primary_issue_id=request.issue_id,
                related_issue_ids=request.related_issue_ids,
                use_langchain=_use_langchain(service),
            )

        if not decision.in_scope:
            raise UnsupportedConsultationIssueError(
                "현재 질문은 A파트 상담 범위가 아닙니다."
            )

        updated_request = request.model_copy(
            update={
                "issue_id": decision.primary_issue_id,
                "related_issue_ids": list(decision.related_issue_ids),
            }
        )
        return {
            "request": updated_request,
            "route_decision": decision,
            "route_engine": engine,
        }

    return node


def _ensure_conversation_node(service: Any):
    def node(state: APartGraphState) -> dict[str, Any]:
        conversation_id, is_new = service._ensure_conversation(state["request"])
        return {
            "conversation_id": conversation_id,
            "is_new_conversation": is_new,
        }

    return node


def _prepare_documents_node(service: Any):
    def node(state: APartGraphState) -> dict[str, Any]:
        request = state["request"]
        conversation = service.conversation_service.get_state(state["conversation_id"])
        document_types = {item.document_type for item in conversation.documents}

        if {
            DocumentType.LEASE_CONTRACT,
            DocumentType.REGISTRY,
        }.issubset(document_types):
            mode = "combined_documents"
        elif DocumentType.LEASE_CONTRACT in document_types:
            mode = "lease_contract"
        elif DocumentType.REGISTRY in document_types:
            mode = "registry"
        else:
            mode = "general"

        should_analyze = bool(
            (conversation.documents or request.document_ids)
            and not conversation.document_analysis_version
            and (
                request.analyze_documents
                or bool(request.document_ids)
                or requests_document_review(request.question)
            )
        )
        return {
            "document_mode": mode,
            "should_analyze_documents": should_analyze,
            "warnings": list(state.get("warnings") or []),
        }

    return node


def _document_branch(state: APartGraphState) -> str:
    return (
        "analyze_documents"
        if state.get("should_analyze_documents")
        else "reuse_documents"
    )


def _analyze_documents_node(service: Any):
    def node(state: APartGraphState) -> dict[str, Any]:
        request = state["request"]
        response = service.document_service.analyze_documents(
            conversation_id=state["conversation_id"],
            document_ids=(request.document_ids or None),
            force=request.force_document_analysis,
            apply_state_mapping=True,
        )
        return {
            "document_analysis": response,
            "warnings": [
                *(state.get("warnings") or []),
                *response.warnings,
            ],
        }

    return node


def _reuse_documents_node(service: Any):
    def node(state: APartGraphState) -> dict[str, Any]:
        request = state["request"]
        conversation = service.conversation_service.get_state(state["conversation_id"])
        warnings = list(state.get("warnings") or [])
        response = None

        if conversation.documents and conversation.document_analysis_version:
            response = service.document_service.analyze_documents(
                conversation_id=state["conversation_id"],
                document_ids=(request.document_ids or None),
                force=False,
                apply_state_mapping=False,
            )
            warnings.extend(response.warnings)
        elif request.document_ids:
            warnings.append(
                "첨부 문서는 아직 분석되지 않았습니다. 문서 검토 질문을 다시 보내 주세요."
            )

        return {
            "document_analysis": response,
            "warnings": warnings,
        }

    return node


def _plan_query_node(service: Any):
    def node(state: APartGraphState) -> dict[str, Any]:
        request = state["request"]
        route_decision = state["route_decision"]
        document_analysis = state.get("document_analysis")
        conversation = service.conversation_service.get_state(state["conversation_id"])
        known_facts = confirmed_fact_sentences(conversation, max_items=10)

        document_context = service._document_rag_query(
            user_question=request.question,
            document_analysis=document_analysis,
        )

        if document_context:
            fallback_query = document_context
        elif not state.get("is_new_conversation") and conversation.initial_query:
            # 진행 중 추가 질문은 짧은 답변 자체가 아니라 최초 상황을 검색한다.
            fallback_query = conversation.initial_query
        else:
            fallback_query = route_decision.search_query or request.question

        query_override, engine = plan_search_query(
            user_question=request.question,
            route_decision=route_decision,
            known_facts=known_facts,
            document_context=document_context,
            fallback_query=fallback_query,
            use_langchain=_use_langchain(service),
        )
        rag_options = dict(request.rag_options)
        rag_options["query_override"] = query_override

        if document_analysis is not None:
            rag_options["apply_state_policy"] = False
            rag_options["build_follow_up_questions"] = True
            rag_options["suppress_no_update_warning"] = True

        return {
            "rag_options": rag_options,
            "query_planner_engine": engine,
        }

    return node


def _consultation_node(service: Any):
    def node(state: APartGraphState) -> dict[str, Any]:
        request = state["request"]
        consultation = service.conversation_service.handle(
            request.question,
            conversation_id=state["conversation_id"],
            issue_id=request.issue_id,
            related_issue_ids=request.related_issue_ids,
            slot_updates=request.checklist_updates or None,
            rag_options=state.get("rag_options") or {},
        )
        consultation = service._apply_document_summary(
            consultation,
            state.get("document_analysis"),
        )
        consultation = consultation.model_copy(
            update={"is_new_conversation": state.get("is_new_conversation", False)}
        )
        return {"consultation": consultation}

    return node


def _finalize_node(service: Any):
    def node(state: APartGraphState) -> dict[str, Any]:
        from app.consultation.a_part.chatbot_service import ChatbotTurnResult

        consultation = state["consultation"]
        status = service._processing_status(consultation)
        result = ChatbotTurnResult(
            conversation_id=state["conversation_id"],
            processing_status=status,
            answer_ready=consultation.answer_ready,
            is_new_conversation=state.get("is_new_conversation", False),
            document_analysis=state.get("document_analysis"),
            consultation=consultation,
            warnings=[
                *(state.get("warnings") or []),
                *consultation.warnings,
            ],
            orchestration={
                "graph_version": GRAPH_VERSION,
                "framework": "langgraph",
                "route_engine": state.get("route_engine", "unknown"),
                "query_planner_engine": state.get("query_planner_engine", "unknown"),
                "document_mode": state.get("document_mode", "general"),
                "primary_issue_id": state["route_decision"].primary_issue_id,
                "related_issue_ids": list(state["route_decision"].related_issue_ids),
            },
        )
        return {"result": result}

    return node


def build_a_part_graph(service: Any):
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as error:
        raise RuntimeError(
            "langgraph 패키지가 설치되지 않아 A파트 그래프를 만들 수 없습니다."
        ) from error

    builder = StateGraph(APartGraphState)
    builder.add_node("route", _route_node(service))
    builder.add_node("ensure_conversation", _ensure_conversation_node(service))
    builder.add_node("prepare_documents", _prepare_documents_node(service))
    builder.add_node("analyze_documents", _analyze_documents_node(service))
    builder.add_node("reuse_documents", _reuse_documents_node(service))
    builder.add_node("plan_query", _plan_query_node(service))
    builder.add_node("consultation", _consultation_node(service))
    builder.add_node("finalize", _finalize_node(service))

    builder.add_edge(START, "route")
    builder.add_edge("route", "ensure_conversation")
    builder.add_edge("ensure_conversation", "prepare_documents")
    builder.add_conditional_edges(
        "prepare_documents",
        _document_branch,
        {
            "analyze_documents": "analyze_documents",
            "reuse_documents": "reuse_documents",
        },
    )
    builder.add_edge("analyze_documents", "plan_query")
    builder.add_edge("reuse_documents", "plan_query")
    builder.add_edge("plan_query", "consultation")
    builder.add_edge("consultation", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


def run_a_part_graph(service: Any, request: Any):
    graph_app = getattr(service, "_a_part_graph_app", None)
    if graph_app is None:
        graph_app = build_a_part_graph(service)
        setattr(service, "_a_part_graph_app", graph_app)

    output = graph_app.invoke(
        {
            "request": request,
            "warnings": [],
            "rag_options": {},
        }
    )
    return output["result"]


# 서비스 의존성을 받아 컴파일된 그래프를 반환하는 공식 진입점이다.
graph = build_a_part_graph
