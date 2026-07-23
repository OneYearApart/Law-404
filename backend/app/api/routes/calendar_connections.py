"""사용자별 Google Calendar MCP connection 관리 API."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    update_calendar_connection_status,
    upsert_calendar_connection,
)
from app.calendar_connections.smithery_client import (
    SmitheryApiError,
    SmitheryConfigError,
    create_or_update_google_calendar_connection,
    get_smithery_connection,
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
    authorization_url = None

    if connection is not None and provider == DEFAULT_CALENDAR_PROVIDER:
        try:
            smithery_connection = await get_smithery_connection(
                connection_id=connection.connection_id,
            )
            authorization_url = smithery_connection.authorization_url
            if (
                smithery_connection.status
                and smithery_connection.status != connection.status
            ):
                connection = update_calendar_connection_status(
                    db,
                    connection=connection,
                    status=smithery_connection.status,
                )
        except (SmitheryConfigError, SmitheryApiError):
            # Smithery 상태 확인 실패가 채팅 사용 자체를 막지 않도록 DB 상태를 반환합니다.
            authorization_url = None

    return CalendarConnectionStatusResponse(
        connected=connection is not None and connection.status == "connected",
        provider=provider,
        status=connection.status if connection is not None else None,
        authorization_url=authorization_url,
        connection=(
            CalendarConnectionPublic.model_validate(connection)
            if connection is not None
            else None
        ),
    )


@router.post("/connect", response_model=CalendarConnectGuideResponse)
async def start_calendar_connection(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    connection_id = _build_suggested_connection_id(user.id)

    try:
        smithery_connection = await create_or_update_google_calendar_connection(
            connection_id=connection_id,
            user_id=user.id,
            user_label=f"Law-404 Google Calendar user {user.id}",
        )
    except SmitheryConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Smithery API 설정이 필요합니다. "
                "backend/.env에 SMITHERY_API_KEY, SMITHERY_NAMESPACE를 추가해 주세요."
            ),
        ) from exc
    except SmitheryApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "message": "Smithery connection 생성에 실패했습니다.",
                "status_code": exc.status_code,
                "payload": exc.payload,
            },
        ) from exc

    upsert_calendar_connection(
        db,
        user_id=user.id,
        request=CalendarConnectionUpsertRequest(
            provider=DEFAULT_CALENDAR_PROVIDER,
            connection_id=smithery_connection.connection_id or connection_id,
            connection_name=smithery_connection.name or connection_id,
            status=smithery_connection.status,
        ),
    )

    if smithery_connection.authorization_url:
        note = (
            "Google Calendar 권한 승인이 필요합니다. "
            "authorization_url로 이동해 OAuth 승인을 완료해 주세요."
        )
    elif smithery_connection.connected:
        note = "Google Calendar connection이 이미 연결되어 있습니다."
    else:
        note = "Smithery connection이 생성되었지만 추가 확인이 필요합니다."

    return CalendarConnectGuideResponse(
        status=smithery_connection.status,
        connection_id=smithery_connection.connection_id or connection_id,
        authorization_url=smithery_connection.authorization_url,
        connected=smithery_connection.connected,
        note=note,
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
