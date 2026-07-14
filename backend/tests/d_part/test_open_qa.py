"""
open_qa 노드 테스트 (DB/네트워크는 monkeypatch로 흉내).
"""
import pytest

from app.graph.parts.d_part.nodes import open_qa
from app.rag.retrievers.base import Chunk


async def _fake_search(query: str, top_k: int = 5):
    return [Chunk(id=1, source_type="법령원문", content="관련 조문")]


async def _fake_generate_response(context: str):
    yield "open_qa 응답"


@pytest.mark.asyncio
async def test_handle_open_qa_searches_unrestricted_and_generates_response(monkeypatch):
    seen = {}

    async def _fake_search_and_capture(query: str, top_k: int = 5):
        seen["query"] = query
        seen["top_k"] = top_k
        return [Chunk(id=1, source_type="법령원문", content="관련 조문")]

    monkeypatch.setattr(open_qa._retriever, "search", _fake_search_and_capture)
    monkeypatch.setattr(open_qa.llm_d_part, "generate_response", _fake_generate_response)

    state = {"user_input": "보증금 반환청구 소송은 어떻게 진행하나요"}

    result = await open_qa.handle_open_qa(state)

    assert seen["query"] == "보증금 반환청구 소송은 어떻게 진행하나요"
    assert seen["top_k"] == 5
    assert len(result["retrieved_chunks"]) == 1
    assert result["response_stream"] is not None
    chunks = [c async for c in result["response_stream"]]
    assert chunks == ["open_qa 응답"]


@pytest.mark.asyncio
async def test_uses_active_query_over_raw_user_input_when_present(monkeypatch):
    seen = {}

    async def _fake_search_and_capture(query: str, top_k: int = 5):
        seen["query"] = query
        return []

    monkeypatch.setattr(open_qa._retriever, "search", _fake_search_and_capture)
    monkeypatch.setattr(open_qa.llm_d_part, "generate_response", _fake_generate_response)

    state = {"user_input": "네", "active_query": "보증금 반환청구 소송은 어떻게 진행하나요"}

    await open_qa.handle_open_qa(state)

    assert seen["query"] == "보증금 반환청구 소송은 어떻게 진행하나요"
