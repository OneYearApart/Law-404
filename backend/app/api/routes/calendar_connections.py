"""사용자별 Calendar connection 관리 API."""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.orm import User
from app.calendar_connections.models import (
    DEFAULT_CALENDAR_PROVIDER,
    CalendarConnectGuideResponse,
    CalendarConnectionPublic,
    CalendarConnectionStatusResponse,
    CalendarConnectionUpsertRequest,
)
from app.calendar_connections.repository import (
    delete_calendar_connection,
    get_calendar_connection,
    upsert_calendar_connection,
)
from app.core.db import get_db

router = APIRouter(prefix="/calendar", tags=["calendar_connections"])


def _build_suggested_connection_id(user_id: int) -> str:
    return f"law404_googlecalendar_user_{user_id}"


@router.get("/connection", response_model=CalendarConnectionStatusResponse)
async def get_connection_status(
    provider: str = Query(default=DEFAULT_CALENDAR_PROVIDER),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection = get_calendar_connection(db, user_id=user.id, provider=provider)
    return CalendarConnectionStatusResponse(
        connected=connection is not None and connection.status == "connected",
        provider=provider,
        connection=(
            CalendarConnectionPublic.model_validate(connection)
            if connection is not None
            else None
        ),
    )


@router.post("/connect", response_model=CalendarConnectGuideResponse)
async def start_calendar_connection(
    user: User = Depends(get_current_user),
):
    connection_id = _build_suggested_connection_id(user.id)
    return CalendarConnectGuideResponse(
        status="manual_smithery_connection_required",
        suggested_connection_id=connection_id,
        smithery_command=(
            "smithery mcp add googlecalendar "
            f"--id {connection_id} "
            f"--name {connection_id}"
        ),
        note=(
            "현재 단계에서는 Smithery OAuth를 서버가 자동으로 시작하지 않습니다. "
            "위 명령으로 Google Calendar 연결을 완료한 뒤, "
            "POST /calendar/connection에 connection_id를 저장하세요."
        ),
    )


@router.post(
    "/connection",
    response_model=CalendarConnectionPublic,
    status_code=status.HTTP_201_CREATED,
)
async def save_connection(
    request: CalendarConnectionUpsertRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection = upsert_calendar_connection(
        db,
        user_id=user.id,
        request=request,
    )
    return CalendarConnectionPublic.model_validate(connection)


@router.delete("/connection")
async def remove_connection(
    provider: str = Query(default=DEFAULT_CALENDAR_PROVIDER),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    deleted = delete_calendar_connection(db, user_id=user.id, provider=provider)
    return {
        "deleted": deleted,
        "provider": provider,
    }
