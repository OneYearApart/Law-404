"""
대화 요약 생성 (사이드바에 표시할 제목).

Ollama 기반 경량 로컬 모델 사용 (한국어 성능 양호 + 가벼운 모델).
local_model/models/common/ 에서 실제 호출을 담당.
"""
import logging

from app.conversations.repository import load_conversation, update_conversation_title
from app.local_model.models.common.interface import summarize as local_summarize

logger = logging.getLogger(__name__)


async def summarize_conversation(messages: list[str]) -> str:
    return await local_summarize(messages)


async def maybe_summarize_conversation(conversation_id: int, turn_threshold: int) -> None:
    """대화가 turn_threshold의 배수(user+assistant 쌍 기준)에 도달했을 때만 재요약해 title을 갱신합니다."""
    messages = await load_conversation(conversation_id)
    message_threshold = turn_threshold * 2
    if len(messages) == 0 or len(messages) % message_threshold != 0:
        return

    formatted = [f"{m.role}: {m.content}" for m in messages]
    try:
        title = await summarize_conversation(formatted)
    except Exception:
        logger.exception("conversation summarization failed (conversation_id=%s)", conversation_id)
        return

    await update_conversation_title(conversation_id, title)
