"""
action_plan 빌더 테스트 (DB/네트워크/LLM 접근 없는 순수 로직).
판정 라벨·슬롯 상태 분기 + 금칙어 부재 + 개요 수준(서류 미단정)을 검증한다.

문구 상수는 법령 검수 과정에서 바뀔 수 있으므로 완전일치가 아니라 핵심 키워드 `in`으로
검증한다. 금칙어/면책은 단일 출처(_BANNED_JUDGMENT_TERMS/DISCLAIMER)를 직접 import해
값이 바뀌어도 테스트가 따라가도록 한다.
"""
import pytest

from app.graph.parts.d_part.nodes._disclaimer import DISCLAIMER
from app.graph.parts.d_part.nodes import support_data
from app.graph.parts.d_part.nodes.support_appendix import build_action_plan
from app.graph.parts.d_part.nodes.finalize import _BANNED_JUDGMENT_TERMS
from app.graph.parts.d_part.schemas import SlotStatus, VictimJudgment, VictimRequirementSlots


def _all_filled() -> VictimRequirementSlots:
    return VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus.FILLED,
        deposit_under_limit=SlotStatus.FILLED,
        multiple_victims=SlotStatus.FILLED,
        no_intent_to_return=SlotStatus.FILLED,
    )


def test_high_includes_application_support_and_common_blocks():
    text = build_action_plan(VictimJudgment.HIGH, _all_filled())
    assert "피해자 결정" in text          # 신청 가능성 안내
    assert "우선매수권" in text            # 지원수단(경공매 사전)
    assert "임차권등기명령" in text        # 공통 보호조치
    assert "상담" in text                  # 공통 상담


def test_high_pre_vs_post_auction_branch():
    pre = build_action_plan(VictimJudgment.HIGH, _all_filled())
    post_slots = _all_filled()
    post_slots.auction_completed = True
    post = build_action_plan(VictimJudgment.HIGH, post_slots)
    assert "우선매수권" in pre
    assert "우선매수권" not in post
    assert "배당요구" in post or "명도" in post


def test_needs_confirmation_lists_unfilled_slot_guidance():
    slots = VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus.FILLED,
        deposit_under_limit=SlotStatus.UNFILLED,   # 이 요건이 비어 있음
        multiple_victims=SlotStatus.FILLED,
        no_intent_to_return=SlotStatus.FILLED,
    )
    text = build_action_plan(VictimJudgment.NEEDS_CONFIRMATION, slots)
    assert "재평가를 위해" in text
    assert "보증금" in text                # deposit_under_limit 보완 안내
    assert "임차권등기명령" in text        # 공통 보호조치는 추가확인에도 붙는다


def test_needs_confirmation_falls_back_when_no_unfilled_slot():
    """UNFILLED가 하나도 없는데 추가확인이면(방어적 경로) 일반 보완 문구로 폴백한다."""
    text = build_action_plan(VictimJudgment.NEEDS_CONFIRMATION, _all_filled())
    assert "재평가를 위해" in text
    assert "추가로 확인이 필요한 요건" in text


@pytest.mark.parametrize("judgment", [VictimJudgment.HIGH, VictimJudgment.NEEDS_CONFIRMATION])
def test_no_banned_judgment_terms(judgment):
    text = build_action_plan(judgment, _all_filled())
    for term in _BANNED_JUDGMENT_TERMS:
        assert term not in text


@pytest.mark.parametrize("judgment", [VictimJudgment.HIGH, VictimJudgment.NEEDS_CONFIRMATION])
def test_no_duplicate_disclaimer(judgment):
    """면책은 finalize가 붙이므로 빌더 텍스트엔 없어야 한다(중복 방지)."""
    text = build_action_plan(judgment, _all_filled())
    assert DISCLAIMER not in text


def test_present_judgment_treated_as_high_defensively():
    """'있음'은 현재 victim_check가 산출하지 않지만(§8.5), 빌더는 방어적으로 높음과 동일 처리."""
    text = build_action_plan(VictimJudgment.PRESENT, _all_filled())
    assert "피해자 결정" in text


@pytest.mark.parametrize("text", [
    *support_data._SPECIAL_CASE_GUIDANCE.values(),
    support_data._RECOGNIZED_GUIDANCE,
])
def test_recognized_guidance_has_no_banned_terms(text):
    """인지형 안내도 미인지형 액션플랜과 같은 판단언어 규칙을 지킨다(§9.3)."""
    for term in _BANNED_JUDGMENT_TERMS:
        assert term not in text


@pytest.mark.parametrize("text", [
    *support_data._SPECIAL_CASE_GUIDANCE.values(),
    support_data._RECOGNIZED_GUIDANCE,
])
def test_recognized_guidance_has_no_duplicate_disclaimer(text):
    """면책은 finalize가 붙인다 — 여기 적으면 두 번 나간다."""
    assert DISCLAIMER not in text


def test_recognized_guidance_has_no_prevention_advice():
    """이미 피해자로 인정받은 사용자에게 붙는 안내다 — 계약 전 예방 조언이 섞이면 안 된다."""
    assert "계약 전" not in support_data._RECOGNIZED_GUIDANCE
    assert "피해자 결정" in support_data._RECOGNIZED_GUIDANCE
