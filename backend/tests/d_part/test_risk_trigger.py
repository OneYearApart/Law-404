"""
risk_trigger 노드 6개 조건 감지 테스트 (DB 접근 없는 순수 로직).
"""
import pytest

from app.graph.parts.d_part.nodes.risk_trigger import detect_risk_signal


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_input",
    [
        "어제 경매 개시 통지를 받았어요",
        "보증금을 못 받고 있어요",
        "집주인이랑 연락이 안 돼요",
        "임대인이 사망했다는 얘기를 들었어요",
        "소유권이 이전됐다고 해서 놀랐어요",
        "같은 집주인한테 다른 세입자도 피해를 봤대요",
    ],
)
async def test_each_condition_is_detected(user_input):
    state = {"user_input": user_input}

    result = await detect_risk_signal(state)

    assert result["risk_trigger_detected"] is True
    assert result["risk_trigger_reason"] is not None


@pytest.mark.asyncio
async def test_normal_utterance_is_not_detected():
    state = {"user_input": "전세 계약할 때 확정일자는 언제 받아야 하나요?"}

    result = await detect_risk_signal(state)

    assert result["risk_trigger_detected"] is False
    assert result["risk_trigger_reason"] is None


@pytest.mark.asyncio
async def test_single_morpheme_fraud_mention_alone_is_not_detected():
    """'사기' 단일 형태소만으로는 트리거되지 않아야 한다 (노이즈 방지, 종합문서 3.1절)."""
    state = {"user_input": "이거 사기 아닌가요?"}

    result = await detect_risk_signal(state)

    assert result["risk_trigger_detected"] is False
