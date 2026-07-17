"""
【SSE 유틸리티】Server-Sent Events 포맷팅

"""

import json
from typing import Any


def sse_event(event: str, data: Any) -> str:
    """
    하나의 SSE 이벤트 문자열 생성.

    Args:
        event: 이벤트 이름 (프론트 addEventListener의 키)
        data:  JSON 직렬화 가능한 payload

    Returns:
        "event: ...\ndata: ...\n\n" 형태의 완성된 SSE 청크
    """
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def sse_comment(text: str) -> str:
    """
    SSE 주석(콜론으로 시작). 프론트에는 이벤트로 전달되지 않지만,
    프록시/로드밸런서가 연결을 끊지 않도록 하는 keep-alive 핑으로 씁니다.
    """
    return f": {text}\n\n"