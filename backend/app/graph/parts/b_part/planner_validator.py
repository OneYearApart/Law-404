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
        keyword in question
        for keyword in ["망가", "파손", "손해", "손해배상", "피해"]
    )
    if has_defect and has_damage:
        return True

    has_termination_intent = any(
        keyword in question
        for keyword in ["중도해지", "해지", "계약을 끝", "계약 끝", "나가고 싶", "그만 살"]
    )
    if has_defect and has_termination_intent:
        return True

    return False


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

    return {
        "decision": decision,
        "can_continue_with_available_facts": can_continue,
        "context_should_stop": context_should_stop,
        "planner_should_stop": planner_should_stop,
        "context_missing_questions": context_missing_questions[:3],
        "planner_missing_questions": planner_missing_questions[:3],
    }
