"""
attach_action_plan 노드 게이팅 테스트 — 판정 확정 턴에만 action_plan_text를 세팅한다.
종합문서 §14-5: mock이 늘 이상적 응답을 주므로 '판정 경로가 아닌 턴' 제외를 명시 검증한다.
"""
import pytest

from app.graph.parts.d_part.nodes.action_plan import attach_action_plan
from app.graph.parts.d_part.schemas import SlotStatus, VictimJudgment, VictimRequirementSlots


def _slots():
    return VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus.FILLED,
        deposit_under_limit=SlotStatus.FILLED,
        multiple_victims=SlotStatus.FILLED,
        no_intent_to_return=SlotStatus.FILLED,
    )


@pytest.mark.asyncio
async def test_sets_text_when_judgment_just_confirmed():
    state = {
        "needs_response_assembly": True,
        "victim_judgment": VictimJudgment.HIGH,
        "victim_slots": _slots(),
    }
    result = await attach_action_plan(state)
    assert result.get("action_plan_text")


@pytest.mark.asyncio
async def test_noop_when_not_response_assembly_turn():
    """special_cases/open_qa 등 판정 경로가 아닌 턴은 통과, 텍스트 미설정."""
    state = {"victim_judgment": VictimJudgment.HIGH, "victim_slots": _slots()}  # needs_response_assembly 없음
    result = await attach_action_plan(state)
    assert result.get("action_plan_text") is None


@pytest.mark.asyncio
async def test_noop_when_no_judgment():
    state = {"needs_response_assembly": True, "victim_slots": _slots()}         # judgment 없음
    result = await attach_action_plan(state)
    assert result.get("action_plan_text") is None
