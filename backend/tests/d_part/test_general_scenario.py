"""
general_scenario 실행 노드 테스트 (DB/네트워크는 monkeypatch로 흉내).
항목 분류는 supervisor가 이미 끝낸 것으로 가정하고, RAG 검색+응답 조립만 검증한다.
"""
import pytest

from app.graph.parts.d_part.nodes import general_scenario
from app.graph.parts.d_part.schemas import GENERAL_TOPIC_LABELS
from app.rag.retrievers.base import Chunk


def _make_chunk(source_type: str, content: str) -> Chunk:
    return Chunk(id=1, source_type=source_type, content=content)


async def _fake_search_by_topic(topic_key, query_text):
    return {
        "statute": [_make_chunk("법령원문", "관련 조문")],
        "case_law": [_make_chunk("판례", "관련 판례")],
        "cases": [],
        "guides": [_make_chunk("생활법령", "상황적용 안내")],
    }


async def _fake_generate_response(context: str, answer_kind: str):
    yield "원문 "
    yield "해설 "
    yield "상황적용"


@pytest.mark.asyncio
@pytest.mark.parametrize("topic_key", list(GENERAL_TOPIC_LABELS))
async def test_each_topic_produces_response(monkeypatch, topic_key):
    monkeypatch.setattr(general_scenario._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(general_scenario.llm_d_part, "generate_response", _fake_generate_response)

    state = {"user_input": "아무 발화", "general_topic_matched": topic_key}

    result = await general_scenario.handle_general_scenario(state)

    assert result["response_stream"] is not None
    chunks = [c async for c in result["response_stream"]]
    assert chunks == ["원문 ", "해설 ", "상황적용"]
    assert result.get("final_answer") is None
    assert len(result["retrieved_chunks"]) == 3  # statute 1 + case_law 1 + cases 0 + guides 1


@pytest.mark.asyncio
async def test_matches_regardless_of_confirmed_stage(monkeypatch):
    """supervisor는 확정된 계약단계와 무관하게 13개 항목 전체를 대상으로 분류하므로,
    이 노드도 stage를 아예 참조하지 않고 general_topic_matched만으로 동작해야 한다."""
    monkeypatch.setattr(general_scenario._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(general_scenario.llm_d_part, "generate_response", _fake_generate_response)

    # stage 필드 자체가 없어도(또는 다른 단계여도) 정상 동작해야 함
    state = {"user_input": "다가구주택인데 선순위 보증금이 걱정돼요", "general_topic_matched": "전-③다가구_선순위보증금"}

    result = await general_scenario.handle_general_scenario(state)

    assert result["response_stream"] is not None


@pytest.mark.asyncio
async def test_noop_when_final_answer_already_set():
    """stage_router의 확인질문 대기 등 이미 완결된 턴은 건드리지 않는다."""
    state = {
        "user_input": "네",
        "general_topic_matched": "전-①등기부등본_위험신호",
        "final_answer": "말씀하신 내용을 보면 '전' 단계로 보입니다. 맞으신가요?",
    }

    result = await general_scenario.handle_general_scenario(state)

    assert result == state
