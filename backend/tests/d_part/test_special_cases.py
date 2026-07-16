"""
special_cases 실행 노드 테스트 (DB/네트워크는 monkeypatch로 흉내).
작업단위 49: 하드코딩 안내문 → RAG 실행 노드. 카테고리→태그 매핑 + RAG 해설 스트림 +
지원절차 개요 appendix_text를 검증한다(리트리버·generate_response monkeypatch).
"""
import pytest

from app.graph.parts.d_part.nodes import special_cases
from app.rag.retrievers.base import Chunk


def _chunk(st, content):
    return Chunk(id=1, source_type=st, content=content)


@pytest.mark.asyncio
@pytest.mark.parametrize("category,tag", [
    ("임대인 사망/파산", "트리거-임대인사망파산"),
    ("신탁사기", "전-⑤신탁사기"),
    ("다가구주택", "전-③다가구_선순위보증금"),
    ("공인중개사 허위고지", "전-⑥공인중개사_허위고지"),
])
async def test_retrieves_by_mapped_tag_and_sets_stream_and_appendix(monkeypatch, category, tag):
    seen = {}

    async def _fake_search_by_topic(topic_key, query_text):
        seen["tag"] = topic_key
        return {"statute": [_chunk("법령원문", "조문")], "case_law": [_chunk("판례", "판례")],
                "cases": [], "guides": []}

    async def _fake_generate(context):
        yield "해설 상황적용"

    monkeypatch.setattr(special_cases._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(special_cases.llm_d_part, "generate_response", _fake_generate)

    state = {"user_input": "…", "active_query": None, "special_case_matched": category}
    result = await special_cases.match_special_case(state)

    assert seen["tag"] == tag                              # 카테고리→태그 매핑
    assert result["response_stream"] is not None           # RAG 해설 스트림
    assert result["appendix_text"] == special_cases._SPECIAL_CASE_GUIDANCE[category]
    assert len(result["retrieved_chunks"]) == 2


@pytest.mark.asyncio
async def test_pending_final_answer_is_not_overwritten():
    """stage_router 확인질문 대기 중(final_answer 세팅됨)인 턴은 건드리지 않고 통과해야 한다."""
    state = {"user_input": "…", "special_case_matched": "신탁사기",
             "final_answer": "말씀하신 내용을 보면 '전' 단계로 보입니다. 맞으신가요?"}
    result = await special_cases.match_special_case(state)
    assert result["final_answer"].endswith("맞으신가요?")
    assert result.get("response_stream") is None


def test_guidance_has_no_banned_terms():
    from app.graph.parts.d_part.nodes.finalize import _BANNED_JUDGMENT_TERMS
    for text in special_cases._SPECIAL_CASE_GUIDANCE.values():
        for term in _BANNED_JUDGMENT_TERMS:
            assert term not in text
