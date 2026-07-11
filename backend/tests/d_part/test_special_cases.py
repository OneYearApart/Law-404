"""
special_cases 노드 4개 카테고리 매칭 테스트 (DB 접근 없는 순수 로직).
"""
import pytest

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
async def test_unmatched_input_returns_none():
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
