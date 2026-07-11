"""
Conversation 테이블 SQLAlchemy ORM 모델.
파트 무관 공통 도메인 — schema.sql의 conversations 정의를 그대로 포팅한다.
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.core.db import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    part = Column(String(1), nullable=False)  # 'a' | 'b' | 'c' | 'd'
    title = Column(Text, nullable=True)
    state = Column(JSONB, nullable=True)  # 파트별 턴간 carryover 상태 (현재 d파트 전용)
    updated_at = Column(DateTime, server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String(16), nullable=False)  # 'user' | 'assistant'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
