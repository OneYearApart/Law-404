"""사용자별 Calendar connection 저장소."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.calendar_connections.models import (
    DEFAULT_CALENDAR_PROVIDER,
    CalendarConnectionUpsertRequest,
)
from app.calendar_connections.orm import UserCalendarConnection


def get_calendar_connection(
    db: Session,
    *,
    user_id: int,
    provider: str = DEFAULT_CALENDAR_PROVIDER,
) -> UserCalendarConnection | None:
    return (
        db.query(UserCalendarConnection)
        .filter(
            UserCalendarConnection.user_id == user_id,
            UserCalendarConnection.provider == provider,
        )
        .first()
    )


def upsert_calendar_connection(
    db: Session,
    *,
    user_id: int,
    request: CalendarConnectionUpsertRequest,
) -> UserCalendarConnection:
    connection = get_calendar_connection(
        db,
        user_id=user_id,
        provider=request.provider,
    )
    now = datetime.utcnow()

    if connection is None:
        connection = UserCalendarConnection(
            user_id=user_id,
            provider=request.provider,
            connection_id=request.connection_id,
            connection_name=request.connection_name,
            google_email=request.google_email,
            status=request.status,
            last_connected_at=now if request.status == "connected" else None,
        )
        db.add(connection)
    else:
        connection.connection_id = request.connection_id
        connection.connection_name = request.connection_name
        connection.google_email = request.google_email
        connection.status = request.status
        connection.updated_at = now
        if request.status == "connected":
            connection.last_connected_at = now

    db.commit()
    db.refresh(connection)
    return connection


def delete_calendar_connection(
    db: Session,
    *,
    user_id: int,
    provider: str = DEFAULT_CALENDAR_PROVIDER,
) -> bool:
    connection = get_calendar_connection(
        db,
        user_id=user_id,
        provider=provider,
    )
    if connection is None:
        return False

    db.delete(connection)
    db.commit()
    return True
