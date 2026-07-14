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
    assert result["victim_flow_closed"] is True


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
    assert result["victim_flow_closed"] is True
    # 이번 턴에 새로 확정된 판단이므로 응답 조립이 필요하다는 신호가 켜져야 한다
    assert result["needs_response_assembly"] is True


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
    # final_answer는 실제 시스템에서 DPartSessionState에 없어 매 턴 자동으로 리셋되므로
    # (routes/d_part.py가 세션 상태 필드만 다음 턴 입력으로 넘김), 턴 시뮬레이션에서도 동일하게 제거한다.
    for _ in range(4):
        state.pop("final_answer", None)
        state = await check_victim_status(state)

    assert state["victim_fallback"] is True
    assert state["victim_flow_closed"] is True
    assert state.get("victim_judgment") is None


@pytest.mark.asyncio
async def test_reentry_after_closure_resumes_with_existing_slots(monkeypatch):
    """종결된 인터뷰로 supervisor가 다시 라우팅하면(사용자가 새 위험신호를 말한 경우),
    기존 슬롯은 유지한 채 종결 표식만 되돌려 이어간다 — 처음부터 다시 묻지 않는다."""
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
    # fallback으로 종결된 상태에서 슬롯 하나만 채워져 있던 대화방
    state = {
        "user_input": "알고 보니 다른 세입자도 3명이나 피해를 봤대요",
        "victim_slots": VictimRequirementSlots(moved_in_and_fixed_date=SlotStatus.FILLED),
        "victim_fallback": True,
        "victim_flow_closed": True,
        "victim_check_attempts": 3,
    }

    result = await check_victim_status(state)

    assert result["victim_fallback"] is False
    assert result["victim_check_attempts"] == 0
    # 슬롯이 전부 채워졌으므로 곧바로 구제수단 질문 단계로 이어진다(슬롯 재수집 없음)
    assert result["awaiting_relief_confirmation"] is True
    assert result["victim_flow_closed"] is False


@pytest.mark.asyncio
async def test_pending_final_answer_is_not_overwritten(monkeypatch):
    """stage_router 확인질문 대기 중(final_answer 세팅됨)인 턴은 슬롯 추출을 시도하지 않고
    건드리지 않고 통과해야 한다 (같은 턴 안에서 하위 노드가 상위 노드의 미확정 답변을 덮어쓰는
    잠재 버그의 회귀 테스트)."""
    called = False

    async def _fake_call_victim_check(user_input: str, existing_slots: dict) -> dict:
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(victim_check.llm_d_part, "call_victim_check", _fake_call_victim_check)

    state = {
        "user_input": "전입신고랑 확정일자는 받아뒀어요",
        "final_answer": "말씀하신 내용을 보면 '전' 단계로 보입니다. 맞으신가요?",
    }

    result = await check_victim_status(state)

    assert called is False
    assert result["final_answer"] == "말씀하신 내용을 보면 '전' 단계로 보입니다. 맞으신가요?"
    assert result.get("victim_judgment") is None
