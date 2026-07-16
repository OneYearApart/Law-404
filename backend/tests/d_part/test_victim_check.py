"""
victim_check 노드 상태기계 테스트 (DB 접근 없는 순수 로직).
LLM 호출 두 종류(call_victim_check로 슬롯 추출, parse_confirmation으로 구제수단 확인응답 판별)는
monkeypatch로 흉내내고, 노드가 코드로 책임지는 병합/상태기계/판정 로직만 검증한다.
"""
import pytest

from app.graph.parts.d_part.nodes import victim_check
from app.graph.parts.d_part.nodes.victim_check import check_victim_status
from app.graph.parts.d_part.schemas import SlotStatus, VictimJudgment, VictimRequirementSlots


def _fake_call_victim_check(payload: dict):
    async def _fake(user_input: str, existing_slots: dict) -> dict:
        return payload

    return _fake


def _fake_confirmation(answer):
    async def _fake(question: str, user_input: str):
        return answer

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


def _all_filled_slots() -> VictimRequirementSlots:
    return VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus.FILLED,
        deposit_under_limit=SlotStatus.FILLED,
        multiple_victims=SlotStatus.FILLED,
        no_intent_to_return=SlotStatus.FILLED,
    )


@pytest.mark.asyncio
async def test_affirmative_relief_measure_excludes_without_judgment(monkeypatch):
    monkeypatch.setattr(victim_check, "parse_confirmation", _fake_confirmation(True))
    state = {
        "user_input": "네 맞아요",
        "victim_slots": _all_filled_slots(),
        "awaiting_relief_confirmation": True,
    }

    result = await check_victim_status(state)

    assert result["victim_judgment"] is None
    assert result.get("victim_fallback", False) is False
    assert "제외" in result["final_answer"]
    assert result["victim_flow_closed"] is True


@pytest.mark.asyncio
async def test_negative_relief_measure_computes_final_judgment(monkeypatch):
    monkeypatch.setattr(victim_check, "parse_confirmation", _fake_confirmation(False))
    state = {
        "user_input": "아니요 없어요",
        "victim_slots": _all_filled_slots(),
        "awaiting_relief_confirmation": True,
    }

    result = await check_victim_status(state)

    assert result["victim_judgment"] == VictimJudgment.HIGH
    assert result["victim_flow_closed"] is True
    # 이번 턴에 새로 확정된 판단이므로 응답 조립이 필요하다는 신호가 켜져야 한다
    assert result["needs_response_assembly"] is True


@pytest.mark.asyncio
async def test_unclear_relief_answer_never_excludes_and_reasks(monkeypatch):
    """구제수단 게이트에서 확신할 수 없는 응답을 긍정으로 삼키면 실제 피해자가 지원대상에서
    부당 제외된다 — 이 프로젝트에서 가장 위험한 실패 모드라 unclear는 반드시 재질문이어야 한다."""
    monkeypatch.setattr(victim_check, "parse_confirmation", _fake_confirmation(None))
    state = {
        "user_input": "그건 왜 물어보세요?",
        "victim_slots": _all_filled_slots(),
        "awaiting_relief_confirmation": True,
        "victim_check_attempts": 0,
    }

    result = await check_victim_status(state)

    assert result["victim_slots"].has_relief_measure is None
    assert result.get("victim_judgment") is None
    assert result.get("victim_flow_closed", False) is False
    assert result["awaiting_relief_confirmation"] is True
    assert result["victim_check_attempts"] == 1
    assert "제외" not in result["final_answer"]


@pytest.mark.asyncio
async def test_repeated_unclear_relief_answer_triggers_fallback(monkeypatch):
    """구제수단 게이트가 무한 재질문 루프에 빠지지 않고 상한에서 fallback으로 빠져야 한다."""
    monkeypatch.setattr(victim_check, "parse_confirmation", _fake_confirmation(None))
    state = {
        "user_input": "잘 모르겠어요",
        "victim_slots": _all_filled_slots(),
        "awaiting_relief_confirmation": True,
        "victim_check_attempts": 0,
    }

    for _ in range(victim_check._MAX_ATTEMPTS):
        state.pop("final_answer", None)
        state = await check_victim_status(state)

    assert state["victim_fallback"] is True
    assert state["victim_flow_closed"] is True
    assert state["awaiting_relief_confirmation"] is False
    assert state["victim_slots"].has_relief_measure is None
    assert state.get("victim_judgment") is None


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
async def test_filled_slot_is_never_regressed_by_later_unclear(monkeypatch):
    """이미 filled로 확정된 슬롯은 이후 턴의 unclear/unfilled로 되돌아가면 안 된다
    (병합을 프롬프트에 위임했을 때 모델이 지시를 어기면 이미 답한 질문을 다시 묻게 됨)."""
    monkeypatch.setattr(
        victim_check.llm_d_part,
        "call_victim_check",
        _fake_call_victim_check(
            {
                "moved_in_and_fixed_date": "unclear",
                "deposit_under_limit": "unclear",
                "multiple_victims": "unclear",
                "no_intent_to_return": "filled",
                "multiple_victims_reason": None,
                "auction_completed": None,
            }
        ),
    )
    existing = VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus.FILLED,
        deposit_under_limit=SlotStatus.FILLED,
    )
    state = {"user_input": "돌려줄 생각이 없어 보여요", "victim_slots": existing}

    result = await check_victim_status(state)

    assert result["victim_slots"].moved_in_and_fixed_date == SlotStatus.FILLED
    assert result["victim_slots"].deposit_under_limit == SlotStatus.FILLED
    # 이번 턴에 새로 확인된 슬롯은 반영된다
    assert result["victim_slots"].no_intent_to_return == SlotStatus.FILLED


@pytest.mark.asyncio
async def test_auction_completed_true_survives_later_turns(monkeypatch):
    """auction_completed는 슬롯①③을 면제하므로 뒤집히면 판정이 통째로 바뀐다.
    매 턴 LLM이 재판정하더라도 True는 내려오지 않아야 하고, 미언급(null)이 False로 덮어써도 안 된다."""
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
                "auction_completed": None,
            }
        ),
    )
    existing = VictimRequirementSlots(auction_completed=True, no_intent_to_return=SlotStatus.FILLED)
    state = {"user_input": "보증금은 2억이었어요", "victim_slots": existing}

    result = await check_victim_status(state)

    assert result["victim_slots"].auction_completed is True
    # ①③ 면제 + ②④ 충족이므로 곧바로 구제수단 질문 단계로 넘어간다
    assert result["awaiting_relief_confirmation"] is True


@pytest.mark.asyncio
async def test_missing_auction_completed_does_not_default_to_false(monkeypatch):
    """LLM이 auction_completed를 아예 반환하지 않아도 False로 강제되면 안 된다(Optional[bool] 설계)."""
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
            }
        ),
    )
    state = {"user_input": "음 글쎄요", "victim_slots": VictimRequirementSlots()}

    result = await check_victim_status(state)

    assert result["victim_slots"].auction_completed is None


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
