"""
finalize 노드 테스트 (DB/네트워크 접근 없는 순수 로직).
"""
import pytest

from app.graph.parts.d_part.nodes.finalize import finalize_response


@pytest.mark.asyncio
async def test_wraps_existing_final_answer_into_stream():
    state = {"final_answer": "확인 질문입니다"}

    result = await finalize_response(state)

    assert result["response_stream"] is not None
    chunks = [c async for c in result["response_stream"]]
    assert chunks == ["확인 질문입니다"]


@pytest.mark.asyncio
async def test_fallthrough_message_when_no_final_answer():
    state = {}

    result = await finalize_response(state)

    chunks = [c async for c in result["response_stream"]]
    assert chunks == [result["final_answer"]]
    assert result["final_answer"]


@pytest.mark.asyncio
async def test_does_not_overwrite_existing_response_stream():
    async def _existing_stream():
        yield "already set"

    stream = _existing_stream()
    state = {"response_stream": stream, "final_answer": None}

    result = await finalize_response(state)

    assert result["response_stream"] is stream
