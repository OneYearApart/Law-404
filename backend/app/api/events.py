"""
스트리밍 응답 이벤트 스키마 (공통, 아무도 안 건드림).

- loading: 그래프 내부 판단 단계 진행 중 (세부 노드는 노출하지 않음)
- token:   최종 답변 토큰 단위 스트리밍
- done:    종료
"""
from enum import Enum
from typing import Optional, Union
from pydantic import BaseModel


class EventType(str, Enum):
    LOADING = "loading"
    TOKEN = "token"
    DONE = "done"


class StreamEvent(BaseModel):
    type: EventType
    data: Optional[Union[dict, str]] = None
