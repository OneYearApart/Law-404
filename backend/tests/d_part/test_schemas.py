"""DPartSessionState 직렬화 라운드트립.

DPartSessionState는 conversations.state(JSONB)에 그대로 들어갔다 나온다
(저장: model_dump(mode="json") / 로드: model_validate). 중첩 모델이나 enum이
그 왕복에서 깨지면 다음 턴의 상태가 조용히 비어버리므로 여기서 고정한다.
"""
from app.graph.parts.d_part.schemas import (
    DPartSessionState,
    SituationState,
    SlotStatus,
    Stage,
    VictimJudgment,
    VictimRequirementSlots,
)


def test_situation_survives_json_roundtrip():
    """중첩 SituationState가 enum·리스트까지 값 그대로 왕복하는지."""
    original = DPartSessionState(
        situation=SituationState(
            recognized=True,
            stage=Stage.POST,
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
    assert restored.situation.stage is Stage.POST
    assert restored.situation.risk_signals == ["경공매개시", "보증금미반환"]
    assert restored.situation.special_case == "다가구주택"


def test_json_dump_is_primitives_only():
    """JSONB에 들어갈 dict라 enum 객체가 아니라 문자열이어야 한다."""
    dumped = DPartSessionState(
        situation=SituationState(stage=Stage.PRE, recognized=False)
    ).model_dump(mode="json")

    assert dumped["situation"] == {
        "recognized": False,
        "stage": "전",
        "risk_signals": [],
        "topic": None,
        "special_case": None,
    }


def test_session_state_without_situation_key_still_loads():
    """situation 도입 전에 저장된 기존 대화방의 JSONB엔 이 키가 없다 — 하위호환."""
    legacy_raw = {"stage": "중", "persona": "임차인", "victim_check_attempts": 2}

    restored = DPartSessionState.model_validate(legacy_raw)

    assert restored.situation is None
    assert restored.stage is Stage.DURING
    assert restored.persona == "임차인"
