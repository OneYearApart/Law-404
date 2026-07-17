"""Calendar connection API 요청/응답 모델."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


DEFAULT_CALENDAR_PROVIDER = "smithery_googlecalendar"


class CalendarConnectionUpsertRequest(BaseModel):
    provider: str = Field(default=DEFAULT_CALENDAR_PROVIDER, max_length=50)
    connection_id: str
    connection_name: str | None = None
    google_email: str | None = None
    status: str = Field(default="connected", max_length=30)


class CalendarConnectionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    provider: str
    connection_id: str
    connection_name: str | None = None
    google_email: str | None = None
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_connected_at: datetime | None = None


class CalendarConnectionStatusResponse(BaseModel):
    connected: bool
    provider: str = DEFAULT_CALENDAR_PROVIDER
    connection: CalendarConnectionPublic | None = None
    authorization_url: str | None = None
    status: str | None = None


class CalendarConnectGuideResponse(BaseModel):
    provider: str = DEFAULT_CALENDAR_PROVIDER
    status: str
    connection_id: str | None = None
    authorization_url: str | None = None
    connected: bool = False
    note: str
