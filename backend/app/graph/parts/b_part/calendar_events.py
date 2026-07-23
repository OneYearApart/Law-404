"""
B파트 캘린더 이벤트 후보 생성기.

이 모듈은 Rule Engine 계산 결과를 실제 Calendar MCP에 넘기기 전 단계의
"등록 후보 일정 JSON"으로 변환합니다.

현재 지원:
- 계약갱신요구권 행사 가능 시작일
- 계약갱신요구권 행사 마감일
- 임대차 계약 종료일
"""

from __future__ import annotations

from typing import Any


def build_renewal_calendar_events(rule_result: dict[str, Any]) -> list[dict[str, Any]]:
    """
    계약갱신요구권 행사 기간 계산 결과를 캘린더 일정 후보로 변환합니다.
    """
    contract_end_date = rule_result.get("contract_end_date")
    start_date = rule_result.get("renewal_request_start_date")
    deadline = rule_result.get("renewal_request_deadline")

    events: list[dict[str, Any]] = []

    if start_date:
        events.append(
            {
                "title": "계약갱신요구 가능 시작일",
                "date": start_date,
                "description": "오늘부터 계약갱신요구권 행사가 가능합니다.",
                "event_type": "renewal_request_start",
                "source_rule_type": rule_result.get("rule_type"),
                "all_day": True,
            }
        )

    if deadline:
        events.append(
            {
                "title": "계약갱신요구 마감일",
                "date": deadline,
                "description": "이 날짜 전까지 갱신 의사를 통지하는 것이 중요합니다.",
                "event_type": "renewal_request_deadline",
                "source_rule_type": rule_result.get("rule_type"),
                "all_day": True,
            }
        )

    if contract_end_date:
        events.append(
            {
                "title": "임대차 계약 종료일",
                "date": contract_end_date,
                "description": "임대차 계약이 종료되는 날입니다. 갱신 여부와 이사 계획을 확인하세요.",
                "event_type": "contract_end_date",
                "source_rule_type": rule_result.get("rule_type"),
                "all_day": True,
            }
        )

    return events


def build_calendar_event_candidates(
    rule_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Rule Engine 결과 목록을 캘린더 등록 후보 일정 목록으로 변환합니다.

    Calendar MCP를 실제로 호출하기 전, 사용자에게 어떤 일정이 등록될지
    보여주기 위한 중간 JSON입니다.
    """
    events: list[dict[str, Any]] = []

    for rule_result in rule_results:
        if rule_result.get("rule_type") == "renewal_request_period":
            events.extend(build_renewal_calendar_events(rule_result))

    return events


def build_calendar_pending_action(
    calendar_events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """
    캘린더 후보 일정이 있을 때 다음 턴에서 이어서 처리할 pending_action을 만듭니다.

    이 함수는 실제 Calendar MCP를 호출하지 않습니다.
    챗봇이 사용자에게 "등록할까요?"라고 확인하고, 다음 요청에서 같은 events를
    다시 받을 수 있도록 구조화된 상태만 만들어 둡니다.
    """
    if not calendar_events:
        return None

    return {
        "type": "calendar_event_confirmation",
        "status": "pending",
        "prompt": "아래 일정을 캘린더에 등록할까요?",
        "events": calendar_events,
    }


def build_calendar_registration_ready_action(
    pending_action: dict[str, Any],
) -> dict[str, Any] | None:
    """
    사용자 승인이 확인된 pending_action을 Calendar MCP 호출 직전 상태로 바꿉니다.

    아직 실제 캘린더에 등록하지 않고, 어떤 일정을 등록할 준비가 되었는지
    구조화된 JSON으로 반환합니다.
    """
    if pending_action.get("type") != "calendar_event_confirmation":
        return None

    events = pending_action.get("events")
    if not isinstance(events, list) or not events:
        return None

    return {
        "type": "calendar_registration",
        "status": "ready_to_register",
        "events": events,
    }


def format_calendar_events_for_answer(calendar_events: list[dict[str, Any]]) -> str:
    """
    최종 답변에 붙일 캘린더 등록 후보 섹션을 결정적으로 생성합니다.

    날짜와 제목은 LLM이 다시 쓰지 않고, calendar_events JSON 값을 그대로 사용합니다.
    """
    if not calendar_events:
        return ""

    lines = [
        "⑧ 캘린더 등록 가능 일정",
        "아래 일정은 캘린더에 등록할 수 있습니다. 실제 등록 전에는 사용자 확인이 필요합니다.",
        "",
    ]

    for index, event in enumerate(calendar_events, start=1):
        title = event.get("title", "일정")
        event_date = event.get("date", "")
        description = event.get("description", "")

        lines.append(f"{index}. {title}: {event_date}")
        if description:
            lines.append(f"   - {description}")

    return "\n".join(lines).strip()
