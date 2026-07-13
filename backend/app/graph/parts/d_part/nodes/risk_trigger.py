"""
위험신호 감지 노드 (단계 횡단, cross-cutting).

트리거 조건 (발화 내 위험 신호):
- 경매/공매 개시 통지
- 보증금 미반환
- 임대인 연락두절/사망/파산
- 소유권 변동 인지
- 타 세입자 피해 소식

로컬 경량 분류기 도입 후보 지점 — local_model/models/d_part/ 참고.
매 턴마다 도는 로직이라 비용/속도 개선 여지가 큼.
"""
from app.graph.parts.d_part.schemas import DPartGraphState, get_active_query
from app.llm import d_part as llm_d_part

# 1단계: 구(phrase) 단위 키워드 매칭. "사기" 같은 단일 형태소는 무관한 사건을 잘못
# 끌어올 수 있어 의도적으로 쓰지 않는다(종합문서 3.1절 노이즈 사례 참고).
_TRIGGER_CONDITIONS: list[tuple[int, str, tuple[str, ...]]] = [
    (1, "경매/공매 개시 통지를 받았다는 언급", ("경매 개시", "공매 개시", "경매개시결정", "경매 통지", "공매 통지")),
    (2, "보증금을 돌려받지 못하고 있다는 언급", ("보증금을 못 받", "보증금을 안 돌려", "보증금 반환이 안", "보증금을 안 주")),
    (3, "임대인과 연락이 안 된다는 언급", ("연락이 안 돼", "연락을 안 받", "연락 두절", "잠적")),
    (4, "임대인 사망/파산 소식을 들었다는 언급", ("임대인이 사망", "집주인이 사망", "임대인이 파산", "집주인이 파산")),
    (5, "소유권 변동(경매낙찰, 명의이전)을 알게 됐다는 언급", ("명의가 바뀌", "소유권이 이전", "경매로 낙찰", "낙찰이 됐")),
    (6, "같은 집주인에게 다른 세입자도 피해를 봤다는 언급", ("다른 세입자도 피해", "다른 세입자도 당했", "같은 집주인한테 다른")),
]


async def _llm_ambiguous_check(user_input: str) -> tuple[int, str] | None:
    """1단계 키워드 스캔이 못 잡은 애매한 케이스를 LLM으로 보완 판별한다."""
    result = await llm_d_part.call_risk_trigger(user_input)
    if result.get("matched"):
        return result.get("condition_no"), result.get("reason")
    return None


async def detect_risk_signal(state: DPartGraphState) -> DPartGraphState:
    """6개 위험신호 조건을 스캔해 risk_trigger_detected/risk_trigger_reason을 채운다.
    stage_router와 독립적으로 동작하며, carryover 없이 매 턴 새로 판단한다."""
    user_input = get_active_query(state)

    for condition_no, description, keywords in _TRIGGER_CONDITIONS:
        if any(kw in user_input for kw in keywords):
            state["risk_trigger_detected"] = True
            state["risk_trigger_reason"] = description
            return state

    ambiguous = await _llm_ambiguous_check(user_input)
    if ambiguous is not None:
        _, reason = ambiguous
        state["risk_trigger_detected"] = True
        state["risk_trigger_reason"] = reason
        return state

    state["risk_trigger_detected"] = False
    state["risk_trigger_reason"] = None
    return state
