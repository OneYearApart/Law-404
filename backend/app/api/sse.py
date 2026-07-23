"""
【SSE 유틸리티】Server-Sent Events 포맷팅

"""

import json
from typing import Any


def sse_event(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n"


def sse_comment(text: str) -> str:
    return f": {text}\n\n"
