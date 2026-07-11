"""
final_answer가 이미 텍스트로 확정된 턴(확인질문/후속질문/특수상황 안내/폴백 등)을
SSE 토큰 스트림 형태로 통일해서 내보내는 마지막 노드. response_assembly에서 이미
response_stream을 채운 턴(victim_judgment 신규 확정)은 건드리지 않는다.
"""
from typing import AsyncGenerator

from app.graph.parts.d_part.schemas import DPartGraphState

_FALLTHROUGH_MESSAGE = "안내드릴 내용이 없습니다. 어떤 점이 궁금하신가요?"


async def _stream_text(text: str) -> AsyncGenerator[str, None]:
    yield text


async def finalize_response(state: DPartGraphState) -> DPartGraphState:
    if state.get("response_stream") is not None:
        return state

    state["final_answer"] = state.get("final_answer") or _FALLTHROUGH_MESSAGE
    state["response_stream"] = _stream_text(state["final_answer"])
    return state
