"""A파트에서 사용하는 LangChain 구조화 체인.

모델 호출이 실패하거나 LangChain 패키지를 사용할 수 없는 경우에도 기존
규칙 기반 라우터와 원래 질문을 사용해 상담을 계속할 수 있도록 설계한다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.consultation.a_part.issues import ISSUE_DEFINITIONS, get_supported_issue_ids
from app.consultation.a_part.models import ConversationState
from app.consultation.a_part.router import (
    UnsupportedConsultationIssueError,
    route_issues,
)
from app.consultation.a_part.state_updater import (
    SlotExtractionResult,
    _allowed_slot_payload,
)
from app.core.config import settings
from app.graph.parts.a_part.schemas import APartRouteDecision, APartSearchPlan


_ROUTE_SYSTEM_PROMPT = """
너는 Law 404의 A파트인 주택 임대차 계약 진행·입주 초기 상담 라우터다.
사용자 질문을 제공된 q01~q20 중 가장 직접적인 이슈 하나와 관련 이슈 최대 두 개로 분류한다.

규칙:
1. 계약 상대방·대리권·계좌·계약서·등기부·권리관계·계약 직후 절차·보증금 보호와 관련 없으면 in_scope=false다.
2. 비슷한 단어보다 사용자가 실제로 해결하려는 위험을 우선한다.
3. search_query에는 사용자의 구체적인 사실을 유지하면서 공식 법령·절차·안전 자료 검색에 필요한 핵심 용어를 자연스러운 한국어 문장으로 작성한다.
4. 사용자가 말하지 않은 금액·날짜·권한·문서 상태는 만들지 않는다.
5. primary_issue_id와 related_issue_ids에는 제공된 ID만 사용한다.
""".strip()


_SEARCH_SYSTEM_PROMPT = """
너는 Law 404 A파트의 RAG 검색 질의 계획기다.
사용자 질문과 현재 상담 이슈, 이미 확인된 사실, 문서 분석 요약을 받아 공식 법률·계약 절차·전세 안전·문서 분석 근거를 찾기 좋은 검색 문장을 만든다.

규칙:
1. 사용자가 말하지 않았거나 문서에서 확인되지 않은 사실은 추가하지 않는다.
2. 문서에서 위험이 없다고 확인된 항목을 위험이 있다고 뒤집지 않는다.
3. 권리·권한·송금·서명·잔금과 관련된 질문은 확인 및 보류 기준을 검색하도록 표현한다.
4. OCR 또는 문서 판독이 불확실하면 원본 재확인 기준을 포함한다.
5. 검색 문장은 하나의 완결된 한국어 문장으로 작성한다.
""".strip()


_SLOT_SYSTEM_PROMPT = """
너는 Law 404 상담 상태 추출기다.
사용자의 현재 발화에서 명시적으로 확인되는 사실만 허용된 슬롯에 반영한다.

규칙:
1. 허용된 issue_id와 slot_key만 사용한다.
2. 사용자가 말하지 않은 사실은 절대 추측하지 않는다.
3. 예/완료/확인함처럼 분명한 답은 status=confirmed, value=true로 작성한다.
4. 아니요/없음/미완료처럼 분명한 부정 답도 status=confirmed, value=false로 작성한다.
5. 이름·금액·날짜·문구는 사용자가 말한 값을 가능한 그대로 value에 넣는다.
6. 모르겠음·아직 못 봄·확인하지 못함은 status=uncertain으로 작성한다.
7. 현재 상황에 적용되지 않는다고 명시한 경우만 status=not_applicable로 작성한다.
8. 앞선 답을 바꾸는 내용이어도 새 값을 추출하되 기존 값을 임의로 지우지 않는다.
9. conflict 값을 자료로 다시 확인한 뒤 최종 확정한다고 명시한 경우만 resolve_conflict=true로 작성한다.
10. 한 문장에서 여러 슬롯이 확인되면 모두 반환한다.
11. 슬롯과 연결할 수 없는 문장은 updates에 넣지 않고 unparsed_text에 남긴다.
""".strip()


def _issue_catalog() -> str:
    rows = []
    for issue in ISSUE_DEFINITIONS.values():
        rows.append(
            {
                "issue_id": issue.issue_id,
                "name": issue.name,
                "description": issue.description,
                "key_slots": [slot.label for slot in issue.slots[:5]],
            }
        )
    return json.dumps(rows, ensure_ascii=False)


def _chat_model(*, temperature: float = 0.0):
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as error:
        raise RuntimeError("langchain-openai 패키지가 설치되지 않았습니다.") from error

    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.openai_api_key,
        temperature=temperature,
        timeout=35,
        max_retries=2,
    )


def _route_with_rules(
    question: str,
    *,
    primary_issue_id: str | None = None,
    related_issue_ids: list[str] | None = None,
) -> APartRouteDecision:
    routed = route_issues(
        question,
        primary_issue_id=primary_issue_id,
        related_issue_ids=related_issue_ids,
    )
    return APartRouteDecision(
        in_scope=True,
        primary_issue_id=routed.primary_issue_id,
        related_issue_ids=list(routed.related_issue_ids),
        confidence=0.72,
        search_query=question.strip(),
        reason="기존 A파트 규칙 기반 라우터로 분류했습니다.",
    )


def route_question(
    question: str,
    *,
    primary_issue_id: str | None = None,
    related_issue_ids: list[str] | None = None,
    use_langchain: bool = True,
) -> tuple[APartRouteDecision, str]:
    """LangChain 구조화 분류를 우선하고 실패하면 기존 라우터로 대체한다."""

    normalized = " ".join(str(question or "").split()).strip()
    if not normalized:
        raise ValueError("question은 빈 문자열일 수 없습니다.")

    if primary_issue_id:
        return (
            _route_with_rules(
                normalized,
                primary_issue_id=primary_issue_id,
                related_issue_ids=related_issue_ids,
            ),
            "explicit",
        )

    if use_langchain:
        try:
            from langchain_core.prompts import ChatPromptTemplate

            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", _ROUTE_SYSTEM_PROMPT),
                    (
                        "human",
                        "[지원 이슈]\n{issue_catalog}\n\n[사용자 질문]\n{question}",
                    ),
                ]
            )
            structured_model = _chat_model().with_structured_output(
                APartRouteDecision,
                method="json_schema",
            )
            result = (prompt | structured_model).invoke(
                {
                    "issue_catalog": _issue_catalog(),
                    "question": normalized,
                }
            )
            if not result.in_scope:
                raise UnsupportedConsultationIssueError(
                    "현재 질문은 A파트 계약 진행·입주 초기 상담 범위가 아닙니다."
                )
            if result.primary_issue_id in result.related_issue_ids:
                result.related_issue_ids = [
                    item
                    for item in result.related_issue_ids
                    if item != result.primary_issue_id
                ][:2]
            if not result.search_query.strip():
                result.search_query = normalized
            return result, "langchain"
        except UnsupportedConsultationIssueError:
            raise
        except Exception:
            pass

    return _route_with_rules(normalized), "deterministic_fallback"


def plan_search_query(
    *,
    user_question: str,
    route_decision: APartRouteDecision,
    known_facts: list[str],
    document_context: str | None,
    fallback_query: str,
    use_langchain: bool = True,
) -> tuple[str, str]:
    """현재 상태를 반영한 RAG 검색 문장을 생성한다."""

    fallback = " ".join(str(fallback_query or user_question).split()).strip()
    if not use_langchain:
        return fallback, "deterministic"

    try:
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", _SEARCH_SYSTEM_PROMPT),
                (
                    "human",
                    "[사용자 질문]\n{question}\n\n"
                    "[주요 상담 이슈]\n{issue_id}\n\n"
                    "[이미 확인된 사실]\n{known_facts}\n\n"
                    "[문서 분석 문맥]\n{document_context}\n\n"
                    "[기본 검색 문장]\n{fallback_query}",
                ),
            ]
        )
        structured_model = _chat_model().with_structured_output(
            APartSearchPlan,
            method="json_schema",
        )
        result = (prompt | structured_model).invoke(
            {
                "question": user_question,
                "issue_id": route_decision.primary_issue_id,
                "known_facts": json.dumps(known_facts, ensure_ascii=False),
                "document_context": document_context or "없음",
                "fallback_query": fallback,
            }
        )
        query = " ".join(result.query_override.split()).strip()
        if len(query) < 4:
            return fallback, "deterministic_fallback"
        return query, "langchain"
    except Exception:
        return fallback, "deterministic_fallback"


def _looks_like_short_follow_up(value: str) -> bool:
    normalized = " ".join(str(value or "").split()).strip()
    if len(normalized) <= 40:
        return True
    if re.fullmatch(r"[0-9,./년월일원만원\-\s]+", normalized):
        return True
    return False


def should_preserve_active_issue(question: str, state: ConversationState) -> bool:
    """진행 중 추가 질문의 짧은 답을 새 이슈로 오분류하지 않는다."""

    return bool(state.active_question_key and _looks_like_short_follow_up(question))


class LangChainSlotUpdateExtractor:
    """LangChain 구조화 출력으로 후속 답변의 슬롯 값을 추출한다."""

    def __init__(self) -> None:
        try:
            from langchain_core.prompts import ChatPromptTemplate
        except ImportError as error:
            raise RuntimeError("langchain 패키지가 설치되지 않았습니다.") from error

        self._prompt = ChatPromptTemplate.from_messages(
            [
                ("system", _SLOT_SYSTEM_PROMPT),
                (
                    "human",
                    "[활성 슬롯]\n{allowed_slots}\n\n"
                    "[직전 추가 질문]\n{recent_questions}\n\n"
                    "[사용자 발화]\n{user_text}",
                ),
            ]
        )
        self._structured_model = _chat_model().with_structured_output(
            SlotExtractionResult,
            method="json_schema",
        )

    def extract(
        self,
        *,
        user_text: str,
        state: ConversationState,
    ) -> SlotExtractionResult:
        normalized = " ".join(str(user_text or "").split()).strip()
        if not normalized:
            raise ValueError("user_text는 빈 문자열일 수 없습니다.")

        recent_questions: list[str] = []
        if state.last_answer:
            answer = state.last_answer.get("answer", state.last_answer)
            if isinstance(answer, dict):
                recent_questions = list(answer.get("follow_up_questions") or [])[:3]

        result = (self._prompt | self._structured_model).invoke(
            {
                "allowed_slots": json.dumps(
                    _allowed_slot_payload(state),
                    ensure_ascii=False,
                    default=str,
                ),
                "recent_questions": json.dumps(
                    recent_questions,
                    ensure_ascii=False,
                ),
                "user_text": normalized,
            }
        )
        return SlotExtractionResult.model_validate(result)


def supported_issue_ids() -> tuple[str, ...]:
    return get_supported_issue_ids()
