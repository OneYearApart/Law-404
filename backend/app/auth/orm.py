"""
User 테이블 SQLAlchemy ORM 모델.
자체(로컬) 회원가입만 지원 — 닉네임/아이디/비밀번호만 수집.
아이디, 닉네임 모두 중복 불허(유니크 제약).
"""
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from app.core.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    nickname = Column(String(50), unique=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
