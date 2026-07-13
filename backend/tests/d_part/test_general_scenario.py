"""
general_scenario 노드 테스트 (DB/네트워크는 monkeypatch로 흉내).
"""
import pytest

from app.graph.parts.d_part.nodes import general_scenario
from app.graph.parts.d_part.schemas import Stage
from app.rag.retrievers.base import Chunk


def _make_chunk(source_type: str, content: str) -> Chunk:
    return Chunk(id=1, source_type=source_type, content=content)


async def _fake_search_by_topic(topic_key, query_text):
    return {
        "statute": [_make_chunk("법령원문", "관련 조문")],
        "case_law": [_make_chunk("판례", "관련 판례")],
        "cases": [],
    }


async def _fake_generate_response(context: str):
    yield "원문 "
    yield "해설 "
    yield "상황적용"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage,user_input,expected_topic",
    [
        (Stage.PRE, "등기부등본에 근저당이 많이 잡혀있어서 불안해요", "전-①등기부등본_위험신호"),
        (Stage.PRE, "전세가율이랑 HUG 보증보험 가입 여부가 궁금해요", "전-②전세가율_HUG보증보험"),
        (Stage.PRE, "다가구주택인데 선순위 보증금이 걱정돼요", "전-③다가구_선순위보증금"),
        (Stage.PRE, "계약서 특약사항이 좀 이상한 것 같아요", "전-④계약서_특약사항"),
        (Stage.PRE, "이 집이 신탁사 소유라고 하던데요", "전-⑤신탁사기"),
        (Stage.PRE, "공인중개사가 허위로 설명한 것 같아요", "전-⑥공인중개사_허위고지"),
        (Stage.DURING, "소유권 변동이 있었는지 확인하고 싶어요", "중-①소유권_변동모니터링"),
        (Stage.DURING, "근저당이 새로 설정됐다고 들었어요", "중-②근저당_추가설정"),
        (Stage.DURING, "임대인이 세금체납 상태라고 해요", "중-③임대인_세금체납"),
        (Stage.DURING, "갱신 거절을 당할까 봐 걱정이에요", "중-④갱신시점_위험"),
        (Stage.DURING, "다른 세입자도 피해를 봤다고 들었어요", "중-⑤다가구_타세입자_피해"),
        (Stage.POST, "대항력을 잃을까 봐 걱정돼요", "후-①대항력_우선변제권_상실"),
        (Stage.POST, "배당 순위 때문에 이중계약이 문제될까요", "후-②이중계약_배당순위"),
    ],
)
async def test_keyword_match_per_stage(monkeypatch, stage, user_input, expected_topic):
    monkeypatch.setattr(general_scenario._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(general_scenario.llm_d_part, "generate_response", _fake_generate_response)

    state = {"user_input": user_input, "stage": stage}

    result = await general_scenario.handle_general_scenario(state)

    assert result["general_topic_matched"] == expected_topic
    assert result["response_stream"] is not None
    chunks = [c async for c in result["response_stream"]]
    assert chunks == ["원문 ", "해설 ", "상황적용"]
    assert result.get("final_answer") is None
    assert len(result["retrieved_chunks"]) == 2


@pytest.mark.asyncio
async def test_llm_fallback_when_no_keyword_match(monkeypatch):
    async def _fake_call_general_scenario(user_input, stage, topic_choices):
        assert stage == "전"
        assert "전-①등기부등본_위험신호" in topic_choices
        return {"category": "전-⑤신탁사기"}

    monkeypatch.setattr(general_scenario.llm_d_part, "call_general_scenario", _fake_call_general_scenario)
    monkeypatch.setattr(general_scenario._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(general_scenario.llm_d_part, "generate_response", _fake_generate_response)

    state = {"user_input": "이 부동산 관련해서 뭔가 이상해요", "stage": Stage.PRE}

    result = await general_scenario.handle_general_scenario(state)

    assert result["general_topic_matched"] == "전-⑤신탁사기"
    assert result["response_stream"] is not None


@pytest.mark.asyncio
async def test_unmatched_input_leaves_state_without_response(monkeypatch):
    async def _fake_call_general_scenario(user_input, stage, topic_choices):
        return {"category": None}

    monkeypatch.setattr(general_scenario.llm_d_part, "call_general_scenario", _fake_call_general_scenario)

    state = {"user_input": "오늘 날씨 어때요?", "stage": Stage.PRE}

    result = await general_scenario.handle_general_scenario(state)

    assert result["general_topic_matched"] is None
    assert result.get("response_stream") is None


@pytest.mark.asyncio
async def test_noop_when_final_answer_already_set():
    """stage_router의 확인질문 대기 등 이미 완결된 턴은 건드리지 않는다."""
    state = {
        "user_input": "네",
        "stage": Stage.PRE,
        "final_answer": "말씀하신 내용을 보면 '전' 단계로 보입니다. 맞으신가요?",
    }

    result = await general_scenario.handle_general_scenario(state)

    assert result == state
    assert "general_topic_matched" not in result


@pytest.mark.asyncio
async def test_uses_active_query_over_raw_user_input_when_present(monkeypatch):
    """stage_router 확인 게이트를 통과한 턴("네")이 아니라, 스택해둔 실질 질문(active_query)으로
    토픽을 매칭해야 한다 (확인 게이트에서 실질 질문이 유실되는 버그의 회귀 테스트)."""
    monkeypatch.setattr(general_scenario._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(general_scenario.llm_d_part, "generate_response", _fake_generate_response)

    state = {
        "user_input": "네",
        "active_query": "등기부등본에 근저당이 많이 잡혀있어서 불안해요",
        "stage": Stage.PRE,
    }

    result = await general_scenario.handle_general_scenario(state)

    assert result["general_topic_matched"] == "전-①등기부등본_위험신호"
