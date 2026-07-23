"""
B파트 LLM Planner 결과를 graph 실행 전에 검증하는 모듈입니다.

LLM Planner는 사용자의 의도와 부족한 정보를 넓게 추정합니다.
하지만 모든 부족 정보가 답변을 멈춰야 하는 필수 정보는 아닙니다.
예를 들어 월세 인상 질문에서 현재 월세와 요구 월세가 이미 있으면
계약 종료일이 없어도 5% 초과 여부는 Rule Engine으로 계산할 수 있습니다.
"""

from __future__ import annotations

from typing import Any

from app.graph.parts.b_part.rules import parse_money_values_from_text

SUPPORTED_TOOLS = {"rule_engine", "retriever", "calendar_candidate"}

TOOL_ALIASES = {
    "rule": "rule_engine",
    "rules": "rule_engine",
    "rule_engine": "rule_engine",
    "rule engine": "rule_engine",
    "calculator": "rule_engine",
    "retriever": "retriever",
    "retrieve": "retriever",
    "rag": "retriever",
    "vector_search": "retriever",
    "calendar": "calendar_candidate",
    "calendar_candidate": "calendar_candidate",
    "calendar_mcp": "calendar_candidate",
}


def build_planner_missing_questions(planner_result: dict[str, Any]) -> list[str]:
    """Planner가 판단한 필수 부족 정보를 사용자 질문 문장으로 변환합니다."""
    missing_facts = planner_result.get("missing_required_facts")
    if not isinstance(missing_facts, list):
        return []

    question_map = {
        "contract_end_date": "계약 종료일이 언제인지 알려주세요.",
        "contract_notice_date": "집주인 또는 세입자가 갱신 거절이나 조건 변경을 통보한 날짜가 언제인지 알려주세요.",
        "current_rent": "현재 월세가 얼마인지 알려주세요.",
        "requested_rent": "집주인이 요구한 월세가 얼마인지 알려주세요.",
        "recent_rent_increase": "최근 1년 안에 보증금이나 월세를 올린 적이 있는지 알려주세요.",
        "converted_deposit_amount": "월세로 전환하려는 보증금 금액이 얼마인지 알려주세요.",
        "repair_request_date": "집주인에게 수리를 요청한 날짜나 수리 요청 후 지난 기간을 알려주세요.",
        "repair_evidence": "집주인에게 수리를 요청한 문자, 카카오톡, 사진 같은 증거가 있는지 알려주세요.",
        "defect_detail": "어떤 하자나 고장이 있는지 구체적으로 알려주세요.",
    }

    questions: list[str] = []
    for fact in missing_facts:
        key = str(fact).strip()
        question = question_map.get(key)
        if not question:
            continue
        if question not in questions:
            questions.append(question)
    return questions[:3]


def normalize_planner_tools(planner_result: dict[str, Any]) -> list[str]:
    """Planner가 제안한 tools_to_use 값을 내부 도구 이름으로 정규화합니다."""
    raw_tools = planner_result.get("tools_to_use")
    if not isinstance(raw_tools, list):
        return []

    normalized: list[str] = []
    for raw_tool in raw_tools:
        key = str(raw_tool).strip().lower()
        tool = TOOL_ALIASES.get(key)
        if tool and tool not in normalized:
            normalized.append(tool)
    return normalized


def can_continue_with_available_facts(question: str, categories: list[str]) -> bool:
    """
    부족 정보가 있어도 현재 질문만으로 Rule/RAG 답변을 진행할 수 있는지 판단합니다.

    이 함수는 하드코딩 답변을 만드는 곳이 아니라,
    "추가 질문으로 멈출지 / 우선 답변할지"를 결정하는 gate 역할입니다.
    """
    if "차임증감" in categories and len(parse_money_values_from_text(question)) >= 2:
        return True

    has_defect = any(
        keyword in question
        for keyword in ["누수", "보일러", "곰팡이", "결로", "배관", "하자", "수리"]
    )
    has_damage = any(
        keyword in question for keyword in ["망가", "파손", "손해", "손해배상", "피해"]
    )
    if has_defect and has_damage:
        return True

    has_termination_intent = any(
        keyword in question
        for keyword in [
            "중도해지",
            "해지",
            "계약을 끝",
            "계약 끝",
            "나가고 싶",
            "그만 살",
        ]
    )
    if has_defect and has_termination_intent:
        return True

    return False


def has_calendar_request(question: str) -> bool:
    """사용자가 일정 또는 캘린더 등록을 기대하는 질문인지 가볍게 판단합니다."""
    return any(
        keyword in question
        for keyword in ["캘린더", "일정", "등록", "알림", "마감일", "언제부터"]
    )


def has_rule_calculation_signal(question: str, categories: list[str]) -> bool:
    """날짜/금액 계산이 필요한 질문인지 판단합니다."""
    if len(parse_money_values_from_text(question)) >= 2:
        return True
    if any(
        keyword in question
        for keyword in ["계약 종료일", "종료일", "만료일", "갱신", "마감일"]
    ):
        return True
    return any(
        category in categories
        for category in [
            "차임증감",
            "전월세전환",
            "계약갱신",
            "계약갱신요구권",
            "묵시적갱신",
        ]
    )


def build_tool_policy(
    *,
    question: str,
    categories: list[str],
    planner_result: dict[str, Any],
    answer_mode: str,
) -> dict[str, Any]:
    """
    Planner의 tools_to_use를 그대로 믿지 않고, B파트 기본 정책으로 보정합니다.

    일반 법률 답변은 근거 검색이 필요하므로 retriever를 기본 도구로 둡니다.
    날짜/금액 신호가 있으면 rule_engine을 추가하고,
    캘린더 신호가 있으면 calendar_candidate까지 추가합니다.
    """
    tools = normalize_planner_tools(planner_result)

    if answer_mode == "final_answer" and "retriever" not in tools:
        tools.append("retriever")

    if has_rule_calculation_signal(question, categories) and "rule_engine" not in tools:
        tools.append("rule_engine")

    if has_calendar_request(question):
        if "rule_engine" not in tools:
            tools.append("rule_engine")
        if "calendar_candidate" not in tools:
            tools.append("calendar_candidate")

    tools = [tool for tool in tools if tool in SUPPORTED_TOOLS]
    skipped_tools = [tool for tool in sorted(SUPPORTED_TOOLS) if tool not in tools]
    return {
        "tools_to_use": tools,
        "skipped_tools": skipped_tools,
    }


def validate_planner_flow(
    *,
    question: str,
    categories: list[str],
    context_result: dict[str, Any],
    planner_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Context Resolver와 Intent Planner 결과를 실행 제어용 검증 결과로 정리합니다.

    반환값은 graph.py의 missing_scope 노드가 그대로 사용할 수 있는
    작은 의사결정 객체입니다.
    """
    can_continue = can_continue_with_available_facts(question, categories)

    context_missing_questions = context_result.get("required_missing_questions", [])
    if not isinstance(context_missing_questions, list):
        context_missing_questions = []

    planner_missing_questions = build_planner_missing_questions(planner_result)

    context_should_stop = (
        context_result.get("source") == "llm"
        and context_result.get("response_mode") == "ask_missing_info"
        and bool(context_missing_questions)
        and not can_continue
    )

    planner_should_stop = (
        planner_result.get("source") == "llm"
        and planner_result.get("answer_mode") == "ask_missing_info"
        and bool(planner_missing_questions)
        and not can_continue
    )

    if can_continue:
        decision = "continue_with_available_facts"
    elif context_should_stop:
        decision = "ask_context_missing_info"
    elif planner_should_stop:
        decision = "ask_planner_missing_info"
    else:
        decision = "continue"

    tool_policy = build_tool_policy(
        question=question,
        categories=categories,
        planner_result=planner_result,
        answer_mode=str(planner_result.get("answer_mode") or "final_answer"),
    )

    return {
        "decision": decision,
        "can_continue_with_available_facts": can_continue,
        "context_should_stop": context_should_stop,
        "planner_should_stop": planner_should_stop,
        "context_missing_questions": context_missing_questions[:3],
        "planner_missing_questions": planner_missing_questions[:3],
        "tools_to_use": tool_policy["tools_to_use"],
        "skipped_tools": tool_policy["skipped_tools"],
    }
