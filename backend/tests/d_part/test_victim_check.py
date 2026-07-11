"""
victim_check 노드 상태기계 테스트 (DB 접근 없는 순수 로직).
call_victim_check(LLM 호출)는 monkeypatch로 흉내내고, 노드에 남은 병합/상태기계/판정 로직만 검증한다.
"""
import pytest

from app.graph.parts.d_part.nodes import victim_check
from app.graph.parts.d_part.nodes.victim_check import check_victim_status
from app.graph.parts.d_part.schemas import SlotStatus, VictimJudgment, VictimRequirementSlots


def _fake_call_victim_check(payload: dict):
    async def _fake(user_input: str, existing_slots: dict) -> dict:
        return payload

    return _fake


@pytest.mark.asyncio
async def test_initial_freeform_fills_detected_slots_and_asks_next(monkeypatch):
    monkeypatch.setattr(
        victim_check.llm_d_part,
        "call_victim_check",
        _fake_call_victim_check(
            {
                "moved_in_and_fixed_date": "filled",
                "deposit_under_limit": "unclear",
                "multiple_victims": "unclear",
                "no_intent_to_return": "filled",
                "multiple_victims_reason": None,
                "auction_completed": False,
            }
        ),
    )
    state = {"user_input": "작년에 전입신고랑 확정일자는 받아뒀는데 집주인이 돌려줄 생각이 없어 보여요"}

    result = await check_victim_status(state)

    assert result["victim_slots"].moved_in_and_fixed_date == SlotStatus.FILLED
    assert result["victim_slots"].no_intent_to_return == SlotStatus.FILLED
    assert result["victim_slots"].deposit_under_limit == SlotStatus.UNCLEAR
    assert result["final_answer"] is not None
    assert result.get("victim_judgment") is None


@pytest.mark.asyncio
async def test_followup_answer_fills_remaining_slot(monkeypatch):
    monkeypatch.setattr(
        victim_check.llm_d_part,
        "call_victim_check",
        _fake_call_victim_check(
            {
                "moved_in_and_fixed_date": "filled",
                "deposit_under_limit": "filled",
                "multiple_victims": "filled",
                "no_intent_to_return": "filled",
                "multiple_victims_reason": None,
                "auction_completed": False,
            }
        ),
    )
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
async def test_auction_completed_exempts_slots_1_and_3(monkeypatch):
    monkeypatch.setattr(
        victim_check.llm_d_part,
        "call_victim_check",
        _fake_call_victim_check(
            {
                "moved_in_and_fixed_date": "unclear",
                "deposit_under_limit": "filled",
                "multiple_victims": "unclear",
                "no_intent_to_return": "filled",
                "multiple_victims_reason": None,
                "auction_completed": True,
            }
        ),
    )
    state = {
        "user_input": "경공매가 끝났고 보증금은 2억이었어요. 돌려줄 생각이 없어 보여요",
        "victim_slots": VictimRequirementSlots(),
    }

    result = await check_victim_status(state)

    assert result["victim_slots"].auction_completed is True
    # 슬롯①③ 면제, 슬롯②④만 채워지면 전부 해결되어 구제수단 질문으로 넘어가야 함
    assert result["awaiting_relief_confirmation"] is True


@pytest.mark.asyncio
async def test_all_slots_filled_asks_relief_measure_explicitly(monkeypatch):
    monkeypatch.setattr(
        victim_check.llm_d_part,
        "call_victim_check",
        _fake_call_victim_check(
            {
                "moved_in_and_fixed_date": "filled",
                "deposit_under_limit": "filled",
                "multiple_victims": "filled",
                "no_intent_to_return": "filled",
                "multiple_victims_reason": None,
                "auction_completed": False,
            }
        ),
    )
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
    # has_relief_measure 확인은 awaiting_relief_confirmation 분기라 LLM 호출이 없음(명시 예/아니오 판정)
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
    # has_relief_measure 확인은 awaiting_relief_confirmation 분기라 LLM 호출이 없음(명시 예/아니오 판정)
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
async def test_no_progress_repeated_turns_triggers_fallback(monkeypatch):
    monkeypatch.setattr(
        victim_check.llm_d_part,
        "call_victim_check",
        _fake_call_victim_check(
            {
                "moved_in_and_fixed_date": "unclear",
                "deposit_under_limit": "unclear",
                "multiple_victims": "unclear",
                "no_intent_to_return": "unclear",
                "multiple_victims_reason": None,
                "auction_completed": False,
            }
        ),
    )
    state = {"user_input": "음... 잘 모르겠어요"}

    # 1턴째는 슬롯이 미설정(None)에서 명시적 "unclear"로 바뀌는 것 자체가 진전으로 카운트되므로
    # (LLM은 항상 filled/unfilled/unclear 중 하나를 반환하지, None을 반환하지 않음)
    # 진전 없음이 연속으로 잡히는 건 2턴째부터 — MAX_ATTEMPTS(3)에 도달하려면 4턴 필요.
    for _ in range(4):
        state = await check_victim_status(state)

    assert state["victim_fallback"] is True
    assert state.get("victim_judgment") is None
