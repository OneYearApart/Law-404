"""
special_cases 노드 4개 카테고리 매칭 테스트 (DB 접근 없는 순수 로직).
"""
import pytest

from app.graph.parts.d_part.nodes import special_cases
from app.graph.parts.d_part.nodes.special_cases import match_special_case


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_input,expected_category",
    [
        ("임대인이 사망했다고 상속인한테 연락이 왔어요", "임대인 사망/파산"),
        ("이 집이 신탁 등기가 되어 있더라고요", "신탁사기"),
        ("다가구주택인데 선순위 보증금이 많다고 해요", "다가구주택"),
        ("공인중개사 허위고지 때문에 피해를 봤어요", "공인중개사 허위고지"),
    ],
)
async def test_each_category_is_matched(user_input, expected_category):
    state = {"user_input": user_input}

    result = await match_special_case(state)

    assert result["special_case_matched"] == expected_category
    assert result["final_answer"] is not None


@pytest.mark.asyncio
async def test_unmatched_input_returns_none(monkeypatch):
    async def _fake_call_special_cases(user_input: str) -> dict:
        return {"category": None}

    monkeypatch.setattr(special_cases.llm_d_part, "call_special_cases", _fake_call_special_cases)

    state = {"user_input": "전세 계약 갱신은 어떻게 하나요?"}

    result = await match_special_case(state)

    assert result["special_case_matched"] is None


@pytest.mark.asyncio
async def test_already_matched_state_passes_through_unchanged():
    state = {
        "user_input": "아무 말이나 해도 재판정되면 안 됨",
        "special_case_matched": "신탁사기",
    }

    result = await match_special_case(state)

    assert result["special_case_matched"] == "신탁사기"
    assert "final_answer" not in result or result["final_answer"] is None


@pytest.mark.asyncio
async def test_uses_active_query_over_raw_user_input_when_present():
    state = {"user_input": "네", "active_query": "이 집이 신탁 등기가 되어 있더라고요"}

    result = await match_special_case(state)

    assert result["special_case_matched"] == "신탁사기"


@pytest.mark.asyncio
async def test_pending_final_answer_is_not_overwritten():
    """stage_router 확인질문 대기 중(final_answer 세팅됨)인 턴은 건드리지 않고 통과해야 한다
    (같은 턴 안에서 하위 노드가 상위 노드의 미확정 답변을 덮어쓰는 잠재 버그의 회귀 테스트)."""
    state = {
        "user_input": "임대인이 사망했다고 상속인한테 연락이 왔어요",
        "final_answer": "말씀하신 내용을 보면 '전' 단계로 보입니다. 맞으신가요?",
    }

    result = await match_special_case(state)

    assert result["final_answer"] == "말씀하신 내용을 보면 '전' 단계로 보입니다. 맞으신가요?"
    assert result.get("special_case_matched") is None
