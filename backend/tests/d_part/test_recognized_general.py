"""
recognized_general 노드 테스트 (DB/네트워크는 monkeypatch로 흉내).
인정받았지만 특수 4종에도 13개 항목에도 안 걸리는 피해자 경로 — open_qa와 검색은 같고
관점(대응·회복)과 지원절차 개요 첨부가 다르다.
"""
import pytest

from app.graph.parts.d_part.nodes import _open_search, recognized_general
from app.rag.retrievers.base import Chunk


async def _fake_generate_response(context: str, answer_kind: str):
    yield "인지형 응답"


@pytest.mark.asyncio
async def test_generates_response_and_attaches_support_guidance(monkeypatch):
    """근거가 있으면 인지형 관점 응답 + 지원절차 개요 첨부 — 첨부는 special_cases와 대칭이다."""
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
    assert result["appendix_text"] == recognized_general._RECOGNIZED_GUIDANCE
    joined = "".join([c async for c in result["response_stream"]])
    assert joined == "인지형 응답"


@pytest.mark.asyncio
async def test_no_evidence_falls_back_without_guidance(monkeypatch):
    """법령원문 근거가 없으면 open_qa와 똑같이 '근거 없음'으로 빠진다 — 이 경로에만 규칙이
    빠져 있으면 인정받은 사용자에게만 조문을 지어내게 된다.

    지원절차 개요도 붙이지 않는다: finalize는 고정 텍스트 경로에서 appendix_text를 읽지 않아
    첨부해봐야 사용자에게 닿지 않는다(붙인 줄 알고 오해하기 쉬운 자리)."""

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


def test_guidance_has_no_prevention_advice():
    """이미 피해자로 인정받은 사용자에게 붙는 안내다 — 계약 전 예방 조언이 섞이면 안 된다."""
    assert "계약 전" not in recognized_general._RECOGNIZED_GUIDANCE
    assert "피해자 결정" in recognized_general._RECOGNIZED_GUIDANCE
