"""
Conversation / Message 모델.
사이드바 대화 목록은 파트 무관 공통 도메인이며, part 컬럼으로만 구분합니다.
"""
from datetime import datetime
from pydantic import BaseModel


class Conversation(BaseModel):
    id: int
    user_id: int
    part: str            # "a" | "b" | "c" | "d"
    title: str            # 요약 결과 (사이드바 표시용)
    updated_at: datetime


class Message(BaseModel):
    id: int
    conversation_id: int
    role: str             # "user" | "assistant"
    content: str
    created_at: datetime
