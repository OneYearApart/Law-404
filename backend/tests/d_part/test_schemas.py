"""DPartSessionState 직렬화 라운드트립.

DPartSessionState는 conversations.state(JSONB)에 그대로 들어갔다 나온다
(저장: model_dump(mode="json") / 로드: model_validate). 중첩 모델이나 enum이
그 왕복에서 깨지면 다음 턴의 상태가 조용히 비어버리므로 여기서 고정한다.
"""

from app.graph.parts.d_part.schemas import (
    DPartSessionState,
    SituationState,
    SlotStatus,
    VictimJudgment,
    VictimRequirementSlots,
)


def test_situation_survives_json_roundtrip():
    """중첩 SituationState가 enum·리스트까지 값 그대로 왕복하는지."""
    original = DPartSessionState(
        situation=SituationState(
            recognized=True,
            risk_signals=["경공매개시", "보증금미반환"],
            topic="후-①대항력_우선변제권_상실",
            special_case="다가구주택",
        ),
        victim_slots=VictimRequirementSlots(moved_in_and_fixed_date=SlotStatus.FILLED),
        victim_judgment=VictimJudgment.HIGH,
    )

    restored = DPartSessionState.model_validate(original.model_dump(mode="json"))

    assert restored == original
    # 동등성만 보면 중첩 모델이 통째로 None이 돼도 통과할 수 있어 축을 직접 짚는다
    assert restored.situation.recognized is True
    assert restored.situation.risk_signals == ["경공매개시", "보증금미반환"]
    assert restored.situation.special_case == "다가구주택"


def test_json_dump_is_primitives_only():
    """JSONB에 들어갈 dict라 enum 객체가 아니라 문자열이어야 한다."""
    dumped = DPartSessionState(situation=SituationState(recognized=False)).model_dump(
        mode="json"
    )

    assert dumped["situation"] == {
        "recognized": False,
        "risk_signals": [],
        "topic": None,
        "special_case": None,
    }


def test_legacy_session_state_still_loads():
    """이미 저장된 대화방의 JSONB와 하위호환인지 — situation 도입 전 행엔 그 키가 없고,
    반대로 이제 없어진 키(stage/active_query/special_case_matched)가 남아 있는 행도 있다.
    스키마에서 필드를 뺄 때 그 행들이 로드에 실패하면 진행 중인 대화가 통째로 깨진다."""
    legacy_raw = {
        "stage": "중",  # D1로 제거된 축
        "active_query": "예전 질문",  # 게이트가 사라져 제거된 값
        "special_case_matched": "신탁사기",  # situation으로 흡수돼 제거된 스칼라
        "persona": "임차인",
        "victim_check_attempts": 2,
    }

    restored = DPartSessionState.model_validate(legacy_raw)

    assert restored.situation is None
    assert restored.persona == "임차인"
    assert restored.victim_check_attempts == 2
