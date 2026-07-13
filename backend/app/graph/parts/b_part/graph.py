"""
B파트 계약 중 분쟁 MVP 그래프.

현재 단계에서는 LangGraph StateGraph 대신 같은 인터페이스의 얇은 클래스를 둡니다.
FastAPI 라우터가 기대하는 graph.ainvoke(request)를 제공하면서,
질문 의도 분류 -> 부족 정보 확인 -> Retriever 검색 -> GPT 답변 생성을 순서대로 실행합니다.
"""

from __future__ import annotations

import re
from typing import Any

from app.llm.b_part import generate_b_part_answer, stream_text
from app.rag.retrievers.b_part import BPartRetriever
from app.graph.parts.b_part.calendar_events import (
    build_calendar_event_candidates,
    build_calendar_pending_action,
    build_calendar_registration_ready_action,
    format_calendar_events_for_answer,
    is_calendar_registration_approved,
)
from app.graph.parts.b_part.rules import parse_money_values_from_text, run_b_part_rules


B_PART_CATEGORIES = [
    "계약갱신",
    "계약갱신요구권",
    "묵시적갱신",
    "차임증감",
    "전월세전환",
    "임대인의무",
    "수선의무",
    "계약해지",
    "손해배상",
]

CATEGORY_KEYWORDS = {
    "계약갱신요구권": [
        "갱신요구",
        "계약갱신요구권",
        "실거주",
        "갱신 거절",
        "갱신거절",
        "나가라고",
        "연장 거절",
    ],
    "묵시적갱신": ["묵시", "자동연장", "자동 연장", "아무 말", "만료됐는데", "기간이 지났"],
    "차임증감": ["월세", "차임", "임대료", "인상", "올려", "증액", "감액", "5%"],
    "전월세전환": ["전세를 월세", "월세로 전환", "반전세", "전월세전환", "전환율"],
    "수선의무": ["수리", "고장", "누수", "보일러", "곰팡이", "결로", "배관", "하자"],
    "임대인의무": ["못 살", "사용", "수익", "방해", "거주", "집주인 의무", "임대인 의무"],
    "계약해지": ["해지", "중도해지", "나가고 싶", "계약을 끝", "연체", "밀렸"],
    "손해배상": ["손해배상", "배상", "파손", "망가", "피해", "손해"],
    "계약갱신": ["계약 연장", "재계약", "계약갱신", "연장 가능", "만료 전"],
}

CATEGORY_GROUPS = {
    "수선의무": ["수선의무", "임대인의무", "계약해지", "손해배상"],
    "계약해지": ["계약해지", "수선의무", "임대인의무", "손해배상"],
    "손해배상": ["손해배상", "수선의무", "임대인의무", "계약해지"],
    "차임증감": ["차임증감", "전월세전환"],
    "전월세전환": ["전월세전환", "차임증감"],
    "계약갱신요구권": ["계약갱신요구권", "계약갱신", "묵시적갱신"],
    "계약갱신": ["계약갱신", "계약갱신요구권", "묵시적갱신"],
    "묵시적갱신": ["묵시적갱신", "계약갱신", "계약갱신요구권"],
}


def extract_user_question(request: dict[str, Any]) -> str:
    """라우터에서 넘어온 여러 형태의 요청에서 사용자 질문을 꺼냅니다."""
    for key in ("message", "query", "question", "input", "content", "text"):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    messages = request.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()

    raise ValueError("B파트 질문을 찾지 못했습니다. message 또는 query 값을 보내주세요.")


def detect_categories(question: str) -> list[str]:
    """키워드 기반 1차 의도 분류입니다. 이후 LLM Intent Analyzer로 교체할 수 있습니다."""
    scores: dict[str, int] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in question)
        if score:
            scores[category] = score

    if not scores:
        return []

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    primary = ranked[0][0]
    categories = CATEGORY_GROUPS.get(primary, [primary])

    for category, _score in ranked[1:]:
        if category not in categories:
            categories.append(category)

    return [category for category in categories if category in B_PART_CATEGORIES]


def find_missing_questions(question: str, categories: list[str]) -> list[str]:
    """계산이나 판단에 필요한 핵심 정보가 빠졌을 때 추가 질문을 만듭니다."""
    missing: list[str] = []
    has_date = bool(re.search(r"\d{4}[년./-]\s*\d{1,2}|만료|종료|통보|받았", question))

    money_values = parse_money_values_from_text(question)
    has_two_money_values = len(money_values) >= 2

    if any(category in categories for category in ["계약갱신", "계약갱신요구권", "묵시적갱신"]):
        if not has_date:
            missing.append("계약 종료일과 집주인 또는 세입자가 통보한 날짜가 언제인지 알려주세요.")

    if any(category in categories for category in ["차임증감", "전월세전환"]):
        if not has_two_money_values:
            missing.append("현재 월세와 집주인이 요구한 월세가 각각 얼마인지 알려주세요.")
        if "최근" not in question and "1년" not in question:
            missing.append("최근 1년 안에 보증금이나 월세를 올린 적이 있는지 알려주세요.")

    if any(category in categories for category in ["수선의무", "임대인의무", "계약해지", "손해배상"]):
        if "문자" not in question and "카톡" not in question and "증거" not in question:
            missing.append("집주인에게 수리를 요청한 문자, 카카오톡, 사진 같은 증거가 있는지 알려주세요.")
        if "언제" not in question and "며칠" not in question and "개월" not in question:
            missing.append("하자가 언제부터 있었고, 수리 요청 후 얼마나 지났는지 알려주세요.")

    return missing[:3]


def deduplicate_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """여러 카테고리 검색 결과에서 같은 청크가 중복되는 것을 제거합니다."""
    seen: set[str] = set()
    unique_results: list[dict[str, Any]] = []
    for result in results:
        metadata = result.get("metadata") or {}
        key = str(metadata.get("chunk_id") or result.get("id"))
        if key in seen:
            continue
        seen.add(key)
        unique_results.append(result)
    return unique_results


class BPartMVPGraph:
    """FastAPI 라우터와 맞추기 위한 최소 graph 인터페이스입니다."""

    def __init__(self) -> None:
        self.retriever = BPartRetriever()

    async def ainvoke(self, request: dict[str, Any]) -> dict[str, Any]:
        question = extract_user_question(request)
        pending_action = request.get("pending_action")
        if isinstance(pending_action, dict) and is_calendar_registration_approved(question):
            calendar_registration = build_calendar_registration_ready_action(pending_action)
            if calendar_registration:
                answer = (
                    "좋습니다. 아래 일정들을 캘린더에 등록할 준비가 완료되었습니다.\n"
                    "현재 단계에서는 실제 Calendar MCP 호출 전까지 확인했으며, "
                    "Calendar MCP가 연결되면 이 일정들을 그대로 등록하면 됩니다."
                )

                return {
                    "question": question,
                    "categories": [],
                    "rule_results": [],
                    "calendar_events": calendar_registration.get("events", []),
                    "pending_action": None,
                    "calendar_registration": calendar_registration,
                    "missing_questions": [],
                    "retrieved": [],
                    "final_answer": answer,
                    "response_stream": stream_text(answer),
                }

        categories = request.get("categories") or request.get("category")
        if isinstance(categories, str):
            categories = [categories]
        if not categories:
            categories = detect_categories(question)

        top_k = int(request.get("top_k", 5))
        rule_results = run_b_part_rules(question=question, categories=categories)
        calendar_events = build_calendar_event_candidates(rule_results)
        pending_action = build_calendar_pending_action(calendar_events)
        retrieved = self._retrieve(question=question, categories=categories, top_k=top_k)
        missing_questions = find_missing_questions(question, categories)

        answer = generate_b_part_answer(
            user_question=question,
            retrieved_documents=retrieved,
            categories=categories,
            missing_questions=missing_questions,
            rule_results=rule_results,
        )
        calendar_answer_section = format_calendar_events_for_answer(calendar_events)
        if calendar_answer_section:
            answer = f"{answer.rstrip()}\n\n{calendar_answer_section}"

        return {
            "question": question,
            "categories": categories,
            "rule_results": rule_results,
            "calendar_events": calendar_events,
            "pending_action": pending_action,
            "missing_questions": missing_questions,
            "retrieved": retrieved,
            "final_answer": answer,
            "response_stream": stream_text(answer),
        }

    def _retrieve(self, question: str, categories: list[str], top_k: int) -> list[dict[str, Any]]:
        """
        B파트 검색 전략.

        기존 방식은 source_type 구분 없이 similarity 순으로만 검색했기 때문에
        관련성이 낮은 판례가 법령보다 먼저 들어오는 문제가 있었습니다.

        개선 방식:
        1. 예측 카테고리별로 법령(law)을 먼저 검색합니다.
        2. 판례(precedent)는 보조 근거로 적게 검색합니다.
        3. 중복을 제거합니다.
        4. 최종 결과는 법령을 먼저 배치하고, 판례는 뒤에 배치합니다.
        """
        if not categories:
            return [
                result.to_dict()
                for result in self.retriever.search_sync(query=question, top_k=top_k)
            ]

        law_results: list[dict[str, Any]] = []
        precedent_results: list[dict[str, Any]] = []

        search_categories = categories[:4]

        for category in search_categories:
            laws = self.retriever.search_sync(
                query=question,
                top_k=2,
                category=category,
                source_type="law",
            )
            law_results.extend(result.to_dict() for result in laws)

        for category in search_categories:
            precedents = self.retriever.search_sync(
                query=question,
                top_k=1,
                category=category,
                source_type="precedent",
            )
            precedent_results.extend(result.to_dict() for result in precedents)

        law_results = deduplicate_results(law_results)
        precedent_results = deduplicate_results(precedent_results)

        law_results.sort(key=lambda item: item.get("similarity", 0), reverse=True)
        precedent_results.sort(key=lambda item: item.get("similarity", 0), reverse=True)

        combined_results = law_results + precedent_results

        if not combined_results:
            combined_results = [
                result.to_dict()
                for result in self.retriever.search_sync(query=question, top_k=top_k)
            ]

        return combined_results[:top_k]

graph = BPartMVPGraph()
