"""
special_cases 실행 노드 테스트 (DB/네트워크는 monkeypatch로 흉내).
작업단위 49: 하드코딩 안내문 → RAG 실행 노드. 카테고리→태그 매핑 + RAG 해설 스트림을
검증한다(리트리버·generate_response monkeypatch). 지원절차 개요 부착은 이 노드 책임이
아니므로 여기서 검증하지 않는다 — support_appendix가 상황을 보고 정한다(D3).
"""

import pytest

from app.graph.parts.d_part.nodes import special_cases
from app.graph.parts.d_part.schemas import SituationState
from app.rag.retrievers.base import Chunk


def _chunk(st, content):
    return Chunk(id=1, source_type=st, content=content)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category,tag",
    [
        ("임대인 사망/파산", "트리거-임대인사망파산"),
        ("신탁사기", "전-⑤신탁사기"),
        ("다가구주택", "전-③다가구_선순위보증금"),
        ("공인중개사 허위고지", "전-⑥공인중개사_허위고지"),
    ],
)
async def test_retrieves_by_mapped_tag_and_sets_stream(monkeypatch, category, tag):
    seen = {}

    async def _fake_search_by_topic(topic_key, query_text):
        seen["tag"] = topic_key
        return {
            "statute": [_chunk("법령원문", "조문")],
            "case_law": [_chunk("판례", "판례")],
            "cases": [],
            "guides": [],
        }

    async def _fake_generate(context, answer_kind):
        yield "해설 상황적용"

    monkeypatch.setattr(
        special_cases._retriever, "search_by_topic", _fake_search_by_topic
    )
    monkeypatch.setattr(special_cases.llm_d_part, "generate_response", _fake_generate)

    state = {
        "user_input": "…",
        "situation": SituationState(recognized=True, special_case=category),
    }
    result = await special_cases.match_special_case(state)

    assert seen["tag"] == tag  # 카테고리→태그 매핑
    assert result["response_stream"] is not None  # RAG 해설 스트림
    assert len(result["retrieved_chunks"]) == 2
    # 부착은 support_appendix 몫이다 — 이 노드가 몰래 붙이면 결정 지점이 다시 둘로 갈라진다
    assert result.get("appendix_text") is None


@pytest.mark.asyncio
async def test_pending_final_answer_is_not_overwritten():
    """이미 final_answer가 확정된 턴은 건드리지 않고 통과해야 한다."""
    state = {
        "user_input": "…",
        "situation": SituationState(recognized=True, special_case="신탁사기"),
        "final_answer": "이미 확정된 응답",
    }
    result = await special_cases.match_special_case(state)
    assert result["final_answer"] == "이미 확정된 응답"
    assert result.get("response_stream") is None
