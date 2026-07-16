"""
실제 로컬 Ollama 호출 라이브 스모크 테스트. 로컬에 Ollama가 떠 있어야 하므로 기본 pytest
실행에는 포함되지 않는다 — RUN_OLLAMA_LIVE_TESTS=1 환경변수가 있을 때만 동작.
내용 정확성이 아니라 비어있지 않은 문자열이 오는지만 검증한다(모델 응답은 매번 달라질 수 있음).
"""
import os

import pytest

from app.conversations.summarizer import summarize_conversation

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_OLLAMA_LIVE_TESTS"),
    reason="로컬 Ollama 서버 필요 — RUN_OLLAMA_LIVE_TESTS=1로 명시적 실행",
)


@pytest.mark.asyncio
async def test_summarize_conversation_live():
    messages = [
        "user: 전세 계약 만료가 얼마 안 남았는데 보증금을 안 돌려줘요.",
        "assistant: 임대차보호법상 지연손해금을 청구할 수 있습니다.",
    ]
    title = await summarize_conversation(messages)
    assert isinstance(title, str)
    assert len(title) > 0
