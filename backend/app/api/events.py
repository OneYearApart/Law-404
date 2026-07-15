"""
스트리밍 응답 이벤트 스키마 (공통).

- loading: 그래프 내부 판단 단계 진행 중 (세부 노드는 노출하지 않음)
- token:   최종 답변 토큰 단위 스트리밍
- done:    정상 종료
- error:   처리 중 예외 발생 — data에 사용자 친화 문구를 실어 보내고 스트림을 종료한다
           (단위 31, D파트 도입. 다른 파트도 공용으로 사용 가능)
"""
from enum import Enum
from typing import Optional, Union
from pydantic import BaseModel


class EventType(str, Enum):
    LOADING = "loading"
    TOKEN = "token"
    DONE = "done"
    ERROR = "error"


class StreamEvent(BaseModel):
    type: EventType
    data: Optional[Union[dict, str]] = None
