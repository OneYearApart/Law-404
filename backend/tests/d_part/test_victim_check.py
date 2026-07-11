"""
victim_check 노드 상태기계 테스트 (DB 접근 없는 순수 로직).
"""
import pytest

from app.graph.parts.d_part.nodes.victim_check import check_victim_status
from app.graph.parts.d_part.schemas import SlotStatus, VictimJudgment, VictimRequirementSlots


@pytest.mark.asyncio
async def test_initial_freeform_fills_detected_slots_and_asks_next():
    state = {"user_input": "작년에 전입신고랑 확정일자는 받아뒀는데 집주인이 돌려줄 생각이 없어 보여요"}

    result = await check_victim_status(state)

    assert result["victim_slots"].moved_in_and_fixed_date == SlotStatus.FILLED
    assert result["victim_slots"].no_intent_to_return == SlotStatus.FILLED
    assert result["victim_slots"].deposit_under_limit is None
    assert result["final_answer"] is not None
    assert result.get("victim_judgment") is None


@pytest.mark.asyncio
async def test_followup_answer_fills_remaining_slot():
    existing = VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus.FILLED,
        no_intent_to_return=SlotStatus.FILLED,
        multiple_victims=SlotStatus.FILLED,
    )
    state = {"user_input": "보증금은 3억이에요", "victim_slots": existing}

    result = await check_victim_status(state)

    assert result["victim_slots"].deposit_under_limit == SlotStatus.FILLED
    # 모든 필수 슬롯이 채워졌으므로 구제수단 질문으로 넘어간다
    assert result["awaiting_relief_confirmation"] is True


@pytest.mark.asyncio
async def test_auction_completed_exempts_slots_1_and_3():
    state = {
        "user_input": "경공매가 끝났고 보증금은 2억이었어요. 돌려줄 생각이 없어 보여요",
        "victim_slots": VictimRequirementSlots(),
    }

    result = await check_victim_status(state)

    assert result["victim_slots"].auction_completed is True
    # 슬롯①③ 면제, 슬롯②④만 채워지면 전부 해결되어 구제수단 질문으로 넘어가야 함
    assert result["awaiting_relief_confirmation"] is True


@pytest.mark.asyncio
async def test_all_slots_filled_asks_relief_measure_explicitly():
    slots = VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus.FILLED,
        deposit_under_limit=SlotStatus.FILLED,
        multiple_victims=SlotStatus.FILLED,
        no_intent_to_return=SlotStatus.FILLED,
    )
    state = {"user_input": "그 정도예요", "victim_slots": slots}

    result = await check_victim_status(state)

    assert result["awaiting_relief_confirmation"] is True
    assert result.get("victim_judgment") is None


@pytest.mark.asyncio
async def test_affirmative_relief_measure_excludes_without_judgment():
    slots = VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus.FILLED,
        deposit_under_limit=SlotStatus.FILLED,
        multiple_victims=SlotStatus.FILLED,
        no_intent_to_return=SlotStatus.FILLED,
    )
    state = {"user_input": "네 맞아요", "victim_slots": slots, "awaiting_relief_confirmation": True}

    result = await check_victim_status(state)

    assert result["victim_judgment"] is None
    assert result.get("victim_fallback", False) is False
    assert "제외" in result["final_answer"]


@pytest.mark.asyncio
async def test_negative_relief_measure_computes_final_judgment():
    slots = VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus.FILLED,
        deposit_under_limit=SlotStatus.FILLED,
        multiple_victims=SlotStatus.FILLED,
        no_intent_to_return=SlotStatus.FILLED,
    )
    state = {"user_input": "아니요 없어요", "victim_slots": slots, "awaiting_relief_confirmation": True}

    result = await check_victim_status(state)

    assert result["victim_judgment"] == VictimJudgment.HIGH


@pytest.mark.asyncio
async def test_no_progress_repeated_turns_triggers_fallback():
    state = {"user_input": "음... 잘 모르겠어요"}

    for _ in range(3):
        state = await check_victim_status(state)

    assert state["victim_fallback"] is True
    assert state.get("victim_judgment") is None
