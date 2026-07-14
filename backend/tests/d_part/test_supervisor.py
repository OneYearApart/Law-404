"""
supervisor 노드 테스트 (DB 접근 없는 순수 로직).
call_supervisor(LLM tool calling)는 monkeypatch로 흉내낸다.
"""
import pytest

from app.graph.parts.d_part.nodes import supervisor
from app.graph.parts.d_part.nodes.supervisor import run_supervisor
from app.graph.parts.d_part.schemas import SlotStatus, VictimJudgment, VictimRequirementSlots


async def _unreachable_call_supervisor(user_input: str) -> dict:
    raise AssertionError("진행 중인 흐름이 있을 땐 call_supervisor가 호출되면 안 된다")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [
        {"awaiting_relief_confirmation": True},
        {"victim_slots": VictimRequirementSlots(moved_in_and_fixed_date=SlotStatus.FILLED)},
    ],
)
async def test_in_progress_victim_check_skips_llm_call(monkeypatch, state):
    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _unreachable_call_supervisor)
    state = {**state, "user_input": "2억이에요"}

    result = await run_supervisor(state)

    assert result["route_target"] == "victim_check"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "closed_state",
    [
        # 판정 확정
        {"victim_judgment": VictimJudgment.HIGH, "victim_flow_closed": True},
        # 지원대상 제외(victim_judgment는 None으로 남는다)
        {
            "victim_flow_closed": True,
            "victim_slots": VictimRequirementSlots(
                moved_in_and_fixed_date=SlotStatus.FILLED, has_relief_measure=True
            ),
        },
        # fallback
        {"victim_fallback": True, "victim_flow_closed": True},
    ],
)
async def test_closed_victim_flow_is_reclassified(monkeypatch, closed_state):
    """인터뷰가 종결된 뒤엔 슬롯/판정 값이 세션에 남아 있어도 이번 턴 발화를 정상 재분류해야 한다
    (종결 후 모든 후속 턴이 victim_check로 영구히 고정되던 버그의 회귀 테스트)."""

    async def _fake(user_input: str) -> dict:
        return {"category": "open_qa"}

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake)
    state = {**closed_state, "user_input": "전세보증보험은 언제 가입하나요?"}

    result = await run_supervisor(state)

    assert result["route_target"] == "open_qa"


@pytest.mark.asyncio
async def test_victim_interview_category_routes_to_victim_check(monkeypatch):
    async def _fake(user_input: str) -> dict:
        return {"category": "victim_interview"}

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake)

    result = await run_supervisor({"user_input": "보증금을 못 받고 있어요"})

    assert result["route_target"] == "victim_check"


@pytest.mark.asyncio
async def test_special_case_category_routes_and_sets_matched(monkeypatch):
    async def _fake(user_input: str) -> dict:
        return {"category": "special_case:신탁사기"}

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake)

    result = await run_supervisor({"user_input": "신탁 등기가 되어 있고 이미 피해자로 인정받았어요"})

    assert result["route_target"] == "special_cases"
    assert result["special_case_matched"] == "신탁사기"


@pytest.mark.asyncio
async def test_general_topic_category_routes_and_sets_matched(monkeypatch):
    async def _fake(user_input: str) -> dict:
        return {"category": "general_topic:전-①등기부등본_위험신호"}

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake)

    result = await run_supervisor({"user_input": "등기부등본에 근저당이 많이 잡혀있어서 불안해요"})

    assert result["route_target"] == "general_scenario"
    assert result["general_topic_matched"] == "전-①등기부등본_위험신호"


@pytest.mark.asyncio
async def test_open_qa_category_routes_to_open_qa(monkeypatch):
    async def _fake(user_input: str) -> dict:
        return {"category": "open_qa"}

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake)

    result = await run_supervisor({"user_input": "보증금 반환청구 소송은 어떻게 진행하나요"})

    assert result["route_target"] == "open_qa"


@pytest.mark.asyncio
async def test_noop_when_final_answer_already_set(monkeypatch):
    """stage_router 확인질문 대기 중인 턴은 LLM 호출 없이 통과해야 한다."""
    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _unreachable_call_supervisor)
    state = {
        "user_input": "네",
        "final_answer": "말씀하신 내용을 보면 '전' 단계로 보입니다. 맞으신가요?",
    }

    result = await run_supervisor(state)

    assert result == state
    assert "route_target" not in result


@pytest.mark.asyncio
async def test_uses_active_query_over_raw_user_input_when_present(monkeypatch):
    seen_input = {}

    async def _fake(user_input: str) -> dict:
        seen_input["value"] = user_input
        return {"category": "open_qa"}

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake)

    await run_supervisor({"user_input": "네", "active_query": "보증금 반환청구 소송은 어떻게 진행하나요"})

    assert seen_input["value"] == "보증금 반환청구 소송은 어떻게 진행하나요"
