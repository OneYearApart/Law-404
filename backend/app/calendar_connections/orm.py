"""
사용자별 Calendar MCP connection ORM 모델.

현재는 Smithery Google Calendar MCP connection_id를 사용자별로 저장합니다.
실제 tool call에는 connection_name이 아니라 connection_id를 사용합니다.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.auth.orm import User  # noqa: F401  # ForeignKey 대상 users 테이블을 metadata에 등록
from app.core.db import Base


class UserCalendarConnection(Base):
    __tablename__ = "user_calendar_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_user_calendar_provider"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider = Column(String(50), nullable=False, default="smithery_googlecalendar")
    connection_id = Column(String, nullable=False)
    connection_name = Column(String, nullable=True)
    google_email = Column(String, nullable=True)
    status = Column(String(30), nullable=False, default="connected")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    last_connected_at = Column(DateTime, nullable=True)
