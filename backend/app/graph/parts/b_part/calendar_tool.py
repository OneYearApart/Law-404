"""
B파트 Calendar MCP 연동 전 단계의 Adapter 모듈입니다.

현재 단계에서는 실제 외부 캘린더에 일정을 등록하지 않고,
calendar_registration payload를 검증한 뒤 Calendar MCP에 넘길 수 있는
표준 event payload로 변환합니다.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date, timedelta
from typing import Any

import httpx

from app.core.config import settings

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_TIMEZONE = "Asia/Seoul"
KST_OFFSET = "+09:00"
SMITHERY_CONNECTION_NAME = "googlecalendar"
SMITHERY_CREATE_EVENT_TOOL_NAME = "create_event"
SMITHERY_API_BASE_URL = "https://api.smithery.ai"


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


def to_google_calendar_create_event_args(
    event: dict[str, Any],
    *,
    calendar_id: str = "primary",
    timezone_str: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    """
    Google Calendar MCP create_event 호출 인자로 변환합니다.

    Codex Google Calendar MCP의 create_event 스키마 기준:
    - title
    - description
    - start_time: RFC3339 datetime
    - end_time: RFC3339 datetime
    - timezone_str: IANA timezone
    - attendees: 필수 리스트

    현재 B파트 일정은 하루 종일 확인용 일정이므로,
    날짜를 Asia/Seoul 기준 00:00~다음날 00:00 구간으로 변환합니다.
    """
    event_date = date.fromisoformat(str(event["date"]))
    next_date = event_date + timedelta(days=1)
    start_time = f"{event_date.isoformat()}T00:00:00{KST_OFFSET}"
    end_time = f"{next_date.isoformat()}T00:00:00{KST_OFFSET}"

    return {
        "calendar_id": calendar_id or "primary",
        "title": str(event["title"]),
        "description": str(event.get("description", "")),
        "start_time": start_time,
        "end_time": end_time,
        "timezone_str": timezone_str,
        "attendees": [],
        "add_google_meet": False,
        "event_type": "default",
        "transparency": "transparent",
        "self_attendance": "accepted",
    }


def to_smithery_create_event_args(
    event: dict[str, Any],
    *,
    calendar_id: str = "primary",
    timezone_str: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    """
    Smithery Google Calendar MCP의 create_event tool 호출 인자로 변환합니다.

    Smithery 도구는 start_datetime과 duration을 받아 종료 시각을 계산합니다.
    B파트 계약 일정은 날짜 중심 일정이므로 all_day=True인 경우 해당 날짜 00:00부터
    24시간짜리 일정으로 등록합니다.
    """
    event_date = date.fromisoformat(str(event["date"]))
    is_all_day = bool(event.get("all_day", True))

    if is_all_day:
        start_datetime = f"{event_date.isoformat()}T00:00:00"
        duration_hour = 24
        duration_minutes = 0
    else:
        start_datetime = f"{event_date.isoformat()}T09:00:00"
        duration_hour = 1
        duration_minutes = 0

    return {
        "calendar_id": calendar_id or "primary",
        "start_datetime": start_datetime,
        "timezone": timezone_str,
        "event_duration_hour": duration_hour,
        "event_duration_minutes": duration_minutes,
        "summary": str(event["title"]),
        "description": str(event.get("description", "")),
        "attendees": [],
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
    google_create_event_args = [
        to_google_calendar_create_event_args(event) for event in events
    ]
    smithery_create_event_args = [
        to_smithery_create_event_args(event) for event in events
    ]
    return {
        "status": "dry_run",
        "provider": "mock_calendar",
        "event_count": len(converted_events),
        "events": converted_events,
        "google_calendar_create_event_args": google_create_event_args,
        "smithery_create_event_args": smithery_create_event_args,
    }


def _call_smithery_create_event(
    event_args: dict[str, Any],
    *,
    connection_id: str,
) -> dict[str, Any]:
    """Smithery REST API를 우선 사용하고, 로컬 개발에서는 CLI로 fallback합니다."""
    api_key = (settings.smithery_api_key or "").strip()
    if api_key:
        api_result = _call_smithery_create_event_via_api(
            event_args,
            connection_id=connection_id,
            api_key=api_key,
        )
        if api_result.get("ok") or api_result.get("reason") != "smithery_api_failed":
            return api_result

    return _call_smithery_create_event_via_cli(
        event_args,
        connection_id=connection_id,
    )


def _call_smithery_create_event_via_api(
    event_args: dict[str, Any],
    *,
    connection_id: str,
    api_key: str,
) -> dict[str, Any]:
    """Smithery Connect MCP endpoint로 Google Calendar create_event tool을 호출합니다."""
    namespace = (settings.smithery_namespace or "law404").strip()
    url = (
        f"{SMITHERY_API_BASE_URL}/connect/{namespace}/"
        f"{connection_id}/.tools/{SMITHERY_CREATE_EVENT_TOOL_NAME}"
    )

    try:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=event_args,
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "reason": "smithery_api_failed",
            "error": str(exc),
            "event_args": event_args,
        }

    try:
        response_payload = response.json()
    except ValueError:
        return {
            "ok": False,
            "reason": "smithery_api_response_not_json",
            "status_code": response.status_code,
            "text": response.text,
            "event_args": event_args,
        }

    if response.status_code >= 400 or (
        isinstance(response_payload, dict) and response_payload.get("error")
    ):
        return {
            "ok": False,
            "reason": "smithery_api_tool_error",
            "status_code": response.status_code,
            "response": response_payload,
            "event_args": event_args,
        }

    response_data = _extract_smithery_response_data(response_payload)
    return {
        "ok": True,
        "event_args": event_args,
        "response": response_payload,
        "response_data": response_data,
        "provider_event_id": response_data.get("id")
        if isinstance(response_data, dict)
        else None,
        "html_link": response_data.get("htmlLink")
        if isinstance(response_data, dict)
        else None,
    }


def _call_smithery_create_event_via_cli(
    event_args: dict[str, Any],
    *,
    connection_id: str,
) -> dict[str, Any]:
    """Smithery CLI를 통해 Google Calendar MCP create_event tool을 호출합니다."""
    smithery_command = shutil.which("smithery")
    if not smithery_command:
        return {
            "ok": False,
            "reason": "smithery_cli_not_found",
            "event_args": event_args,
        }

    command = [
        smithery_command,
        "tool",
        "call",
        connection_id,
        SMITHERY_CREATE_EVENT_TOOL_NAME,
        json.dumps(event_args, ensure_ascii=False),
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "reason": "smithery_cli_timeout",
            "event_args": event_args,
        }

    if completed.returncode != 0:
        return {
            "ok": False,
            "reason": "smithery_cli_failed",
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "event_args": event_args,
        }

    try:
        response = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "ok": False,
            "reason": "smithery_response_not_json",
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "event_args": event_args,
        }

    if response.get("isError"):
        return {
            "ok": False,
            "reason": "smithery_tool_error",
            "response": response,
            "event_args": event_args,
        }

    response_data = _extract_smithery_response_data(response)
    return {
        "ok": True,
        "event_args": event_args,
        "response": response,
        "response_data": response_data,
        "provider_event_id": response_data.get("id")
        if isinstance(response_data, dict)
        else None,
        "html_link": response_data.get("htmlLink")
        if isinstance(response_data, dict)
        else None,
    }


def _extract_smithery_response_data(response: dict[str, Any]) -> dict[str, Any]:
    """Smithery CLI 응답에서 실제 Google Calendar event payload를 추출합니다."""
    if not isinstance(response, dict):
        return {"value": response}

    result = response.get("result")
    if isinstance(result, dict):
        result_response_data = result.get("response_data")
        if isinstance(result_response_data, dict):
            return result_response_data

        structured_result = result.get("structuredContent")
        if isinstance(structured_result, dict):
            structured_result_response_data = structured_result.get("response_data")
            if isinstance(structured_result_response_data, dict):
                return structured_result_response_data

    direct_response_data = response.get("response_data")
    if isinstance(direct_response_data, dict):
        return direct_response_data

    structured_content = response.get("structuredContent")
    if isinstance(structured_content, dict):
        structured_response_data = structured_content.get("response_data")
        if isinstance(structured_response_data, dict):
            return structured_response_data

    content = response.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text":
                continue
            text = item.get("text")
            if not isinstance(text, str):
                continue
            try:
                parsed_text = json.loads(text)
            except json.JSONDecodeError:
                continue
            parsed_response_data = parsed_text.get("response_data")
            if isinstance(parsed_response_data, dict):
                return parsed_response_data

    return response


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
    google_create_event_args = [
        {
            **event_args,
            "calendar_id": calendar_id or "primary",
        }
        for event_args in dry_run_result.get("google_calendar_create_event_args", [])
    ]

    # TODO(Google Calendar MCP):
    # 여기에 실제 Google Calendar MCP 호출을 연결하세요.
    #
    # 예상 호출 흐름 예시:
    # registered_events = []
    # for event_args in google_create_event_args:
    #     result = google_calendar_mcp.create_event(**event_args)
    #     registered_events.append(
    #         {
    #             "title": event_args["title"],
    #             "start_time": event_args["start_time"],
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
        "google_calendar_create_event_args": google_create_event_args,
        "registered_event_count": 0,
        "registered_events": [],
    }


def register_smithery_google_calendar_events(
    calendar_registration: dict[str, Any] | None,
    *,
    calendar_id: str = "primary",
    timezone_str: str = DEFAULT_TIMEZONE,
    connection_id: str | None = None,
) -> dict[str, Any]:
    """Smithery Google Calendar MCP를 통해 실제 캘린더 일정을 등록합니다."""
    if not connection_id:
        return {
            "status": "calendar_connection_required",
            "provider": "smithery_googlecalendar",
            "reason": "smithery_connection_id_not_found",
            "event_count": 0,
            "events": [],
            "registered_event_count": 0,
            "registered_events": [],
            "failed_event_count": 0,
            "failed_events": [],
        }

    dry_run_result = dry_run_calendar_registration(calendar_registration)
    if dry_run_result.get("status") != "dry_run":
        return {
            **dry_run_result,
            "provider": "smithery_googlecalendar",
        }

    events = (
        calendar_registration.get("events", [])
        if isinstance(calendar_registration, dict)
        else []
    )
    smithery_create_event_args = [
        to_smithery_create_event_args(
            event,
            calendar_id=calendar_id or "primary",
            timezone_str=timezone_str,
        )
        for event in events
    ]

    registered_events: list[dict[str, Any]] = []
    failed_events: list[dict[str, Any]] = []

    for event, event_args in zip(events, smithery_create_event_args, strict=False):
        result = _call_smithery_create_event(
            event_args,
            connection_id=connection_id,
        )
        if result.get("ok"):
            registered_events.append(
                {
                    "title": event.get("title"),
                    "date": event.get("date"),
                    "provider_event_id": result.get("provider_event_id"),
                    "html_link": result.get("html_link"),
                    "event_args": event_args,
                    "response_data": result.get("response_data"),
                }
            )
            continue

        failed_events.append(
            {
                "title": event.get("title"),
                "date": event.get("date"),
                "reason": result.get("reason"),
                "event_args": event_args,
                "details": result,
            }
        )

    if registered_events and failed_events:
        status = "partial_success"
    elif registered_events:
        status = "registered"
    else:
        status = "failed"

    return {
        "status": status,
        "provider": "smithery_googlecalendar",
        "connection_id": connection_id,
        "calendar_id": calendar_id or "primary",
        "event_count": len(events),
        "events": dry_run_result.get("events", []),
        "smithery_create_event_args": smithery_create_event_args,
        "registered_event_count": len(registered_events),
        "registered_events": registered_events,
        "failed_event_count": len(failed_events),
        "failed_events": failed_events,
    }


def run_calendar_registration(
    calendar_registration: dict[str, Any] | None,
    *,
    mode: str = "dry_run",
    provider: str = "google_calendar",
    calendar_id: str = "primary",
    connection_id: str | None = None,
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

    if normalized_provider in {"smithery_googlecalendar", "smithery_google_calendar"}:
        return register_smithery_google_calendar_events(
            calendar_registration,
            calendar_id=calendar_id or "primary",
            connection_id=connection_id,
        )

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
