"""
recognized_general 노드 테스트 (DB/네트워크는 monkeypatch로 흉내).
인정받았지만 특수 4종에도 13개 항목에도 안 걸리는 피해자 경로 — open_qa와 검색은 같고
관점(대응·회복)만 다르다. 지원절차 개요 부착은 support_appendix 몫이라 여기서 안 본다(D3).
"""
import pytest

from app.graph.parts.d_part.nodes import _open_search, recognized_general
from app.rag.retrievers.base import Chunk


async def _fake_generate_response(context: str, answer_kind: str):
    yield "인지형 응답"


@pytest.mark.asyncio
async def test_generates_response_with_recognized_answer_kind(monkeypatch):
    """근거가 있으면 인지형 관점(answer_kind)으로 응답 스트림을 세팅한다."""
    seen = {}

    async def _fake_search_balanced(query: str, quota=None):
        seen["query"] = query
        return [Chunk(id=1, source_type="법령원문", content="전세사기피해자법 제3조")]

    monkeypatch.setattr(_open_search.retriever, "search_balanced", _fake_search_balanced)
    monkeypatch.setattr(recognized_general.llm_d_part, "generate_response", _fake_generate_response)

    state = {"user_input": "피해자로 인정받았는데 이제 무엇을 해야 하나요"}
    result = await recognized_general.handle_recognized_general(state)

    assert seen["query"] == "피해자로 인정받았는데 이제 무엇을 해야 하나요"
    assert result["answer_kind"] == "recognized_general"
    # 부착은 support_appendix 몫 — 이 노드가 붙이면 결정 지점이 다시 갈라진다
    assert result.get("appendix_text") is None
    joined = "".join([c async for c in result["response_stream"]])
    assert joined == "인지형 응답"


@pytest.mark.asyncio
async def test_no_evidence_falls_back_without_guidance(monkeypatch):
    """법령원문 근거가 없으면 open_qa와 똑같이 '근거 없음'으로 빠진다 — 이 경로에만 규칙이
    빠져 있으면 인정받은 사용자에게만 조문을 지어내게 된다."""

    async def _fake_search_balanced(query: str, quota=None):
        return [Chunk(id=1, source_type="판례", content="판례만")]

    monkeypatch.setattr(_open_search.retriever, "search_balanced", _fake_search_balanced)
    monkeypatch.setattr(recognized_general.llm_d_part, "generate_response", _fake_generate_response)

    result = await recognized_general.handle_recognized_general({"user_input": "근거 없는 질문"})

    assert result["final_answer"] == _open_search.NO_EVIDENCE_MESSAGE
    assert result.get("response_stream") is None
    assert result.get("appendix_text") is None
    assert result["retrieved_chunks"] == []


@pytest.mark.asyncio
async def test_uses_active_query_over_raw_user_input(monkeypatch):
    """확인게이트 대기 중 스택된 active_query를 raw user_input보다 우선해 검색한다."""
    seen = {}

    async def _fake_search_balanced(query: str, quota=None):
        seen["query"] = query
        return [Chunk(id=1, source_type="법령원문", content="관련 조문")]

    monkeypatch.setattr(_open_search.retriever, "search_balanced", _fake_search_balanced)
    monkeypatch.setattr(recognized_general.llm_d_part, "generate_response", _fake_generate_response)

    await recognized_general.handle_recognized_general(
        {"user_input": "네", "active_query": "인정받은 뒤 우선매수권은 어떻게 행사하나요"}
    )

    assert seen["query"] == "인정받은 뒤 우선매수권은 어떻게 행사하나요"
