"""
B파트 Calendar MCP 연동 전 단계의 Adapter 모듈입니다.

현재 단계에서는 실제 외부 캘린더에 일정을 등록하지 않고,
calendar_registration payload를 검증한 뒤 Calendar MCP에 넘길 수 있는
표준 event payload로 변환합니다.
"""

from __future__ import annotations

import re
from typing import Any


DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_calendar_event(event: dict[str, Any]) -> list[str]:
    """캘린더 이벤트 1개의 필수 필드와 날짜 형식을 검증합니다."""
    errors: list[str] = []

    required_fields = ["title", "date", "description", "event_type", "all_day"]
    for field in required_fields:
        if field not in event:
            errors.append(f"missing_event_{field}")

    title = event.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("invalid_event_title")

    event_date = event.get("date")
    if not isinstance(event_date, str) or not DATE_PATTERN.match(event_date):
        errors.append("invalid_event_date")

    description = event.get("description")
    if not isinstance(description, str):
        errors.append("invalid_event_description")

    event_type = event.get("event_type")
    if not isinstance(event_type, str) or not event_type.strip():
        errors.append("invalid_event_type")

    all_day = event.get("all_day")
    if not isinstance(all_day, bool):
        errors.append("invalid_event_all_day")

    return errors


def validate_calendar_registration(calendar_registration: dict[str, Any]) -> list[str]:
    """ready_to_register 상태의 calendar_registration payload를 검증합니다."""
    errors: list[str] = []

    if calendar_registration.get("type") != "calendar_registration":
        errors.append("invalid_registration_type")
    if calendar_registration.get("status") != "ready_to_register":
        errors.append("invalid_registration_status")

    events = calendar_registration.get("events")
    if not isinstance(events, list) or not events:
        errors.append("missing_registration_events")
        return errors

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            errors.append(f"invalid_event_{index}")
            continue
        for error in validate_calendar_event(event):
            errors.append(f"event_{index}_{error}")

    return errors


def to_calendar_mcp_event(event: dict[str, Any]) -> dict[str, Any]:
    """
    내부 calendar event를 Calendar MCP 호출용 payload로 변환합니다.

    실제 MCP provider별 필드명은 후속 작업에서 이 함수를 기준으로 맞추면 됩니다.
    """
    event_date = str(event["date"])
    return {
        "summary": str(event["title"]),
        "description": str(event.get("description", "")),
        "start": {"date": event_date},
        "end": {"date": event_date},
        "all_day": bool(event.get("all_day", True)),
        "metadata": {
            "event_type": event.get("event_type"),
            "source_rule_type": event.get("source_rule_type"),
        },
    }


def dry_run_calendar_registration(
    calendar_registration: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    실제 Calendar MCP 호출 없이 등록 가능한 payload인지 검증하고 변환 결과를 반환합니다.
    """
    if not isinstance(calendar_registration, dict):
        return {
            "status": "skipped",
            "provider": "mock_calendar",
            "reason": "calendar_registration_not_found",
            "event_count": 0,
            "events": [],
        }

    errors = validate_calendar_registration(calendar_registration)
    if errors:
        return {
            "status": "invalid",
            "provider": "mock_calendar",
            "reason": "invalid_calendar_registration",
            "errors": errors,
            "event_count": 0,
            "events": [],
        }

    events = calendar_registration["events"]
    converted_events = [to_calendar_mcp_event(event) for event in events]
    return {
        "status": "dry_run",
        "provider": "mock_calendar",
        "event_count": len(converted_events),
        "events": converted_events,
    }


def register_google_calendar_events(
    calendar_registration: dict[str, Any] | None,
    *,
    calendar_id: str = "primary",
) -> dict[str, Any]:
    """
    Google Calendar MCP 실제 등록을 위한 Adapter 진입점입니다.

    현재 코드에는 실제 MCP 클라이언트가 주입되어 있지 않으므로,
    payload 검증과 변환까지만 수행하고 실제 호출 위치를 TODO로 남깁니다.

    필요한 작업:
    1. Google Calendar MCP 연결 또는 플러그인/서버 설정
    2. 아래 converted_events를 Google Calendar MCP create event 호출에 전달
    3. MCP 응답에서 event id/htmlLink 등을 registered_events에 저장
    4. 일부 실패 시 partial_success 형태로 반환
    """
    dry_run_result = dry_run_calendar_registration(calendar_registration)
    if dry_run_result.get("status") != "dry_run":
        return {
            **dry_run_result,
            "provider": "google_calendar",
        }

    converted_events = dry_run_result["events"]

    # TODO(Google Calendar MCP):
    # 여기에 실제 Google Calendar MCP 호출을 연결하세요.
    #
    # 예상 호출 흐름 예시:
    # registered_events = []
    # for event in converted_events:
    #     result = google_calendar_mcp.create_event(
    #         calendar_id=calendar_id,
    #         summary=event["summary"],
    #         description=event["description"],
    #         start=event["start"],
    #         end=event["end"],
    #     )
    #     registered_events.append(
    #         {
    #             "summary": event["summary"],
    #             "date": event["start"]["date"],
    #             "provider_event_id": result["id"],
    #             "html_link": result.get("htmlLink"),
    #         }
    #     )
    #
    # 실제 MCP 연결 전에는 외부 상태 변경을 막기 위해 not_configured를 반환합니다.
    return {
        "status": "not_configured",
        "provider": "google_calendar",
        "reason": "google_calendar_mcp_not_connected",
        "calendar_id": calendar_id,
        "event_count": len(converted_events),
        "events": converted_events,
        "registered_event_count": 0,
        "registered_events": [],
    }


def run_calendar_registration(
    calendar_registration: dict[str, Any] | None,
    *,
    mode: str = "dry_run",
    provider: str = "google_calendar",
    calendar_id: str = "primary",
) -> dict[str, Any]:
    """
    calendar_registration을 실행 모드에 맞게 처리합니다.

    mode:
    - dry_run: 실제 등록 없이 payload 검증과 변환만 수행
    - live: provider별 실제 등록 함수 호출
    """
    normalized_mode = (mode or "dry_run").strip().lower()
    normalized_provider = (provider or "google_calendar").strip().lower()

    if normalized_mode != "live":
        return dry_run_calendar_registration(calendar_registration)

    if normalized_provider == "google_calendar":
        return register_google_calendar_events(
            calendar_registration,
            calendar_id=calendar_id or "primary",
        )

    return {
        "status": "failed",
        "provider": normalized_provider,
        "reason": "unsupported_calendar_provider",
        "event_count": 0,
        "events": [],
        "registered_event_count": 0,
        "registered_events": [],
    }
