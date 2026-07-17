"""
open_qa 노드 테스트 (DB/네트워크는 monkeypatch로 흉내).
단위 28: search_balanced(쿼터+임계값) 사용 + 법령원문 근거가 없으면 '근거 없음' 폴백.
검색과 폴백 규칙은 recognized_general과 공유하므로 _open_search가 소유한다.
"""
import pytest

from app.graph.parts.d_part.nodes import _open_search, open_qa
from app.rag.retrievers.base import Chunk


async def _fake_generate_response(context: str, answer_kind: str):
    yield "open_qa 응답"


@pytest.mark.asyncio
async def test_generates_response_when_statute_present(monkeypatch):
    """법령원문 근거가 있으면 원문→해설→상황적용 응답을 생성한다."""
    seen = {}

    async def _fake_search_balanced(query: str, quota=None):
        seen["query"] = query
        return [
            Chunk(id=1, source_type="법령원문", content="관련 조문"),
            Chunk(id=2, source_type="판례", content="관련 판례"),
        ]

    monkeypatch.setattr(_open_search.retriever, "search_balanced", _fake_search_balanced)
    monkeypatch.setattr(open_qa.llm_d_part, "generate_response", _fake_generate_response)

    state = {"user_input": "보증금 반환청구 소송은 어떻게 진행하나요"}
    result = await open_qa.handle_open_qa(state)

    assert seen["query"] == "보증금 반환청구 소송은 어떻게 진행하나요"
    assert len(result["retrieved_chunks"]) == 2
    assert result["response_stream"] is not None
    assert result.get("final_answer") is None
    chunks = [c async for c in result["response_stream"]]
    assert chunks == ["open_qa 응답"]


@pytest.mark.asyncio
async def test_no_evidence_when_no_chunks(monkeypatch):
    """검색 결과가 비면 억지 생성 없이 '근거 없음' 문구로 빠진다(response_stream 미생성)."""

    async def _fake_search_balanced(query: str, quota=None):
        return []

    monkeypatch.setattr(_open_search.retriever, "search_balanced", _fake_search_balanced)
    monkeypatch.setattr(open_qa.llm_d_part, "generate_response", _fake_generate_response)

    state = {"user_input": "관련 근거가 전혀 없는 질문"}
    result = await open_qa.handle_open_qa(state)

    assert result["final_answer"] == _open_search.NO_EVIDENCE_MESSAGE
    assert result.get("response_stream") is None


@pytest.mark.asyncio
async def test_no_evidence_when_no_statute(monkeypatch):
    """법령원문 없이 판례/HUG만 걸리면(원문 근거 부재) '근거 없음'으로 빠진다 — 조문 지어내기 방지."""

    async def _fake_search_balanced(query: str, quota=None):
        return [
            Chunk(id=1, source_type="판례", content="판례만"),
            Chunk(id=2, source_type="HUG규정", content="규정만"),
        ]

    monkeypatch.setattr(_open_search.retriever, "search_balanced", _fake_search_balanced)
    monkeypatch.setattr(open_qa.llm_d_part, "generate_response", _fake_generate_response)

    state = {"user_input": "판례만 걸리는 질문"}
    result = await open_qa.handle_open_qa(state)

    assert result["final_answer"] == _open_search.NO_EVIDENCE_MESSAGE
    assert result.get("response_stream") is None


@pytest.mark.asyncio
async def test_no_evidence_clears_retrieved_chunks(monkeypatch):
    """법령원문이 없어 '근거 없음'으로 빠지면 판례/HUG가 걸렸어도 retrieved_chunks를 비운다
    — 라우트가 META 근거 카드를 안 내보내 '근거 없음' 메시지와 모순되지 않게(단위 46)."""

    async def _fake_search_balanced(query: str, quota=None):
        return [
            Chunk(id=1, source_type="판례", content="판례만"),
            Chunk(id=2, source_type="HUG규정", content="규정만"),
        ]

    monkeypatch.setattr(_open_search.retriever, "search_balanced", _fake_search_balanced)
    monkeypatch.setattr(open_qa.llm_d_part, "generate_response", _fake_generate_response)

    state = {"user_input": "판례만 걸리는 질문"}
    result = await open_qa.handle_open_qa(state)

    assert result["retrieved_chunks"] == []             # 카드 미노출 조건


@pytest.mark.asyncio
async def test_context_carries_the_user_question(monkeypatch):
    """자유질의 경로는 "질문과 관련된 법령을 설명하라"는 지시를 받으면서 정작 질문을 컨텍스트에
    못 받고 있었다 — 검색만 발화에 반응하고 생성은 근거만 보던 grounding 불일치."""
    seen = {}

    async def _fake_search_balanced(query: str, quota=None):
        return [Chunk(id=1, source_type="법령원문", content="관련 조문")]

    async def _capture(context: str, answer_kind: str):
        seen["context"] = context
        yield "응답"

    monkeypatch.setattr(_open_search.retriever, "search_balanced", _fake_search_balanced)
    monkeypatch.setattr(open_qa.llm_d_part, "generate_response", _capture)

    result = await open_qa.handle_open_qa({"user_input": "보증금 반환청구 소송은 어떻게 진행하나요"})
    [c async for c in result["response_stream"]]

    assert "보증금 반환청구 소송은 어떻게 진행하나요" in seen["context"]
    assert "관련 조문" in seen["context"]
