"""
User 모델.
자체(로컬) 회원가입만 지원 — 닉네임/아이디/비밀번호만 수집.
"""
from datetime import datetime
from pydantic import BaseModel


class User(BaseModel):
    id: int
    username: str          # 로그인용 아이디 (유니크 제약)
    password_hash: str
    nickname: str
    created_at: datetime


class UserPublic(BaseModel):
    """API 응답용. password_hash는 제외."""
    id: int
    username: str
    nickname: str
    created_at: datetime


class SignupRequest(BaseModel):
    username: str
    nickname: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    """refresh_token은 바디에 담지 않고 httpOnly 쿠키로 전달한다."""
    access_token: str
    token_type: str = "bearer"
