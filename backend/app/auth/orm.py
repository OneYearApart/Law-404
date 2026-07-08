"""
User 테이블 SQLAlchemy ORM 모델.
자체(로컬) 회원가입만 지원 — 닉네임/아이디/비밀번호만 수집.
아이디, 닉네임 모두 중복 불허(유니크 제약).
"""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from app.core.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    nickname = Column(String(50), unique=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class RefreshToken(Base):
    """
    발급된 refresh token은 원문이 아니라 SHA256 해시로 저장한다.
    (32바이트 랜덤값이라 bcrypt 같은 느린 해시는 불필요 — DB 유출 시 원문 노출만 막으면 됨)
    revoked_at이 채워지면 만료 전이어도 더 이상 유효하지 않다 (로그아웃/rotation 시 사용).
    """
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String, unique=True, nullable=False)
    # timezone=True: 만료/폐기 판정을 aware UTC(datetime.now(timezone.utc))로 비교하기 때문
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
