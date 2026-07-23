"""
Conversation / Message 모델.
사이드바 대화 목록은 파트 무관 공통 도메인이며, part 컬럼으로만 구분합니다.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Conversation(BaseModel):
    id: int
    user_id: int
    part: str  # "a" | "b" | "c" | "d"
    title: str | None = (
        None  # 요약 결과. summarizer가 채우기 전(생성 직후~첫 요약)엔 NULL —
    )
    # 사이드바 표시는 ConversationSummary를 쓸 것(제목 폴백 포함)
    updated_at: datetime
    state: dict[str, Any] | None = (
        None  # 파트별 턴간 carryover 상태(JSONB). 파트 무관 컬럼이라 dict로만 선언 —
    )
    # 실제 형태 검증/캐스팅은 각 파트 책임 (d파트: DPartSessionState)


class ConversationSummary(BaseModel):
    """사이드바 대화 목록 한 줄. Conversation과 달리 state(JSONB 전체)를 싣지 않는다 —
    목록은 매 턴 여러 번 갱신되므로 행마다 상태 덤프를 실어 보내면 대역폭이 낭비된다.

    title은 요약(conversations.title)이 붙기 전까지 NULL이라, 그대로 내보내면 사이드바가
    빈 제목을 그린다. 폴백에 필요한 첫 사용자 발화는 messages 테이블에 있어 클라이언트가
    대신 채울 수 없으므로(목록 응답에 메시지가 없다) 여기서 채워 내려준다.
    """

    id: int  # 생성 응답(Conversation)과 같은 이름 — 한 도메인에서 같은 값을 두 이름으로 부르지 않는다
    part: str  # "a" | "b" | "c" | "d" — 클라이언트가 파트별로 골라 쓴다
    title: str
    updated_at: datetime


class Message(BaseModel):
    id: int
    conversation_id: int
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime


class CreateConversationRequest(BaseModel):
    part: Literal["a", "b", "c", "d"]
    title: str | None = Field(default=None, max_length=200)


class CreateMessageRequest(BaseModel):
    part: Literal["a", "b", "c", "d"]
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)
