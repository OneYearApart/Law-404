"""
support_appendix — 지원절차 안내 부착의 단일 결정 지점.
부착 여부·내용이 실행 경로가 아니라 상황모델+판정에서만 나오는지 검증한다(D3).
종합문서 §14-5: mock이 늘 이상적 응답을 주므로 '붙이면 안 되는 턴' 제외를 명시 검증한다.
"""

import pytest

from app.graph.parts.d_part.nodes import support_data
from app.graph.parts.d_part.nodes.support_appendix import (
    attach_support_appendix,
    build_support_appendix,
)
from app.graph.parts.d_part.schemas import (
    SituationState,
    SlotStatus,
    VictimJudgment,
    VictimRequirementSlots,
)


def _slots():
    return VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus.FILLED,
        deposit_under_limit=SlotStatus.FILLED,
        multiple_victims=SlotStatus.FILLED,
        no_intent_to_return=SlotStatus.FILLED,
    )


async def _stream():
    yield "본문"


# ── 무엇을 붙일지는 상황이 정한다 ──────────────────────────────────


@pytest.mark.parametrize("special_case", list(support_data._SPECIAL_CASE_GUIDANCE))
def test_recognized_with_special_case_gets_that_guidance(special_case):
    text = build_support_appendix(
        SituationState(recognized=True, special_case=special_case),
        False,
        None,
        _slots(),
    )
    assert text == support_data._SPECIAL_CASE_GUIDANCE[special_case]


def test_recognized_without_special_case_gets_common_guidance():
    """예전엔 이 사용자가 아무 안내도 못 받았다 — special_cases만이 인지형 안내를 붙였기 때문(D3)."""
    text = build_support_appendix(
        SituationState(recognized=True), False, None, _slots()
    )
    assert text == support_data._RECOGNIZED_GUIDANCE


def test_newly_judged_unrecognized_gets_action_plan():
    text = build_support_appendix(
        SituationState(recognized=False), True, VictimJudgment.HIGH, _slots()
    )
    assert support_data._APPLY_STEP in text


def test_unrecognized_without_judgment_gets_nothing():
    assert (
        build_support_appendix(SituationState(recognized=False), False, None, _slots())
        is None
    )


def test_no_situation_yet_gets_nothing():
    """아직 분류되지 않은 턴(situation 없음)에 안내를 지어내지 않는다."""
    assert build_support_appendix(None, False, None, _slots()) is None


# ── 경로가 아니라 상황이 정한다는 것의 증거 ──────────────────────────


def test_recognized_with_topic_still_gets_guidance():
    """인정받은 사용자는 어느 노드가 답변을 만들었든 같은 안내를 받는다 — 부착이 실행 경로에
    묶여 있던 시절엔 topic이 잡혔다는 이유만으로(general_scenario) 안내가 사라졌다."""
    situation = SituationState(recognized=True, topic="후-②이중계약_배당순위")

    assert (
        build_support_appendix(situation, False, None, _slots())
        == support_data._RECOGNIZED_GUIDANCE
    )


def test_carried_over_judgment_does_not_reattach():
    """victim_judgment는 carryover다 — 이번 턴에 새로 확정(newly_judged)한 게 아니면 붙이지
    않는다. 안 그러면 판정 이후 대화방의 모든 턴에 액션플랜이 재부착된다."""
    assert (
        build_support_appendix(
            SituationState(recognized=False), False, VictimJudgment.HIGH, _slots()
        )
        is None
    )


def test_newly_judged_wins_over_stale_situation():
    """인터뷰 진행 턴은 재분류를 건너뛰어 situation이 직전 값으로 남는다 — 이번 턴 확정 사실인
    판정이 먼저다."""
    text = build_support_appendix(
        SituationState(recognized=True), True, VictimJudgment.HIGH, _slots()
    )
    assert support_data._APPLY_STEP in text


# ── 노드 게이팅 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_node_attaches_on_stream_turn():
    state = {
        "response_stream": _stream(),
        "situation": SituationState(recognized=True),
        "victim_slots": _slots(),
    }
    result = await attach_support_appendix(state)
    assert result["appendix_text"] == support_data._RECOGNIZED_GUIDANCE


@pytest.mark.asyncio
async def test_node_skips_fixed_text_turn():
    """확인질문/fallback/'근거 없음'처럼 스트림이 없는 턴 — finalize가 고정 텍스트 경로에서
    appendix_text를 읽지 않으므로 붙여봐야 사용자에게 닿지 않는다."""
    state = {
        "final_answer": "요건을 하나 더 확인할게요. 전입신고는 하셨나요?",
        "situation": SituationState(recognized=True),
    }
    result = await attach_support_appendix(state)
    assert result.get("appendix_text") is None


@pytest.mark.asyncio
async def test_node_noop_when_nothing_to_attach():
    state = {
        "response_stream": _stream(),
        "situation": SituationState(recognized=False),
    }
    result = await attach_support_appendix(state)
    assert result.get("appendix_text") is None
