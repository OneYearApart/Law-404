"""
special_cases 실행 노드 테스트 (DB 접근 없는 순수 로직).
카테고리 분류는 supervisor가 이미 끝낸 것으로 가정하고, 안내문 조립만 검증한다.
"""
import pytest

from app.graph.parts.d_part.nodes.special_cases import match_special_case


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category",
    ["임대인 사망/파산", "신탁사기", "다가구주택", "공인중개사 허위고지"],
)
async def test_each_category_produces_guidance(category):
    state = {"user_input": "아무 발화", "special_case_matched": category}

    result = await match_special_case(state)

    assert result["final_answer"] is not None


@pytest.mark.asyncio
async def test_reentry_regenerates_guidance_instead_of_noop():
    """이전엔 이미 matched면 no-op만 하고 끝나 후속 대화가 fallthrough로 빠지는 문제가
    있었다 — 이제는 재진입해도 매번 안내문을 다시 만들어야 한다."""
    state = {"user_input": "그럼 상속인은 어떻게 찾나요", "special_case_matched": "신탁사기"}

    result = await match_special_case(state)

    assert result["final_answer"] is not None


@pytest.mark.asyncio
async def test_pending_final_answer_is_not_overwritten():
    """stage_router 확인질문 대기 중(final_answer 세팅됨)인 턴은 건드리지 않고 통과해야 한다."""
    state = {
        "user_input": "임대인이 사망했다고 상속인한테 연락이 왔어요",
        "special_case_matched": "임대인 사망/파산",
        "final_answer": "말씀하신 내용을 보면 '전' 단계로 보입니다. 맞으신가요?",
    }

    result = await match_special_case(state)

    assert result["final_answer"] == "말씀하신 내용을 보면 '전' 단계로 보입니다. 맞으신가요?"
