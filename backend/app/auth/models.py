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
