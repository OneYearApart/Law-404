"""
분류 supervisor 노드 — 예전 risk_trigger/recognition_router/special_cases와
general_scenario의 매칭부를 흡수해 카테고리 판단을 한 곳으로 모은 노드.

아직 종결되지 않은 victim_check 인터뷰(슬롯 채우는 중 / 구제수단 확인 대기)가 있으면
재분류 없이 그대로 이어간다. special_case_matched는 여기서 우선순위 대상으로 보지
않는다 — special_cases는 후속 대화가 없는 1회성 안내라, victim_check 슬롯 인터뷰처럼
"이번 턴 발화 자체가 분류 불가능한 답변"이 되는 경우가 없다. 오히려 재분류를 막으면 안내
이후 사용자가 말을 이어갈 때마다 매번 예전 안내문으로만 되돌아가게 된다.

분류가 필요한 턴은 LLM tool calling 1회로 상황의 축(인지여부·계약단계·위험신호·topic·특수상황)을
한 번에 판별해 state["situation"]에 담는다(call_supervisor). 호출은 1회 그대로다 — 축이 늘었다고
축마다 호출하면 여러 노드로 쪼개져 있던 시절의 비용으로 되돌아간다.

라우팅은 그 상황모델에서 규칙으로 파생시킨다(route) — LLM에게 "어디로 보낼까"를 묻지 않는다.
축을 어떻게 조합해 경로를 정하는지는 도메인이 고정해둔 규칙이라 매 턴 추론할 값이 아니고,
순수함수라 LLM 호출 없이 그대로 테스트할 수 있다. special_case/general_topic은 그 실행 노드가
바로 조회할 수 있도록 special_case_matched/general_topic_matched에 값을 채워 넘긴다.
"""
from typing import Optional

from app.graph.parts.d_part.schemas import (
    DPartGraphState,
    SITUATION_TOPIC_TO_SPECIAL_CASE,
    SituationState,
    Stage,
    VictimRequirementSlots,
    get_active_query,
)
from app.llm import d_part as llm_d_part

_SLOT_FIELDS = ("moved_in_and_fixed_date", "deposit_under_limit", "multiple_victims", "no_intent_to_return")


def _has_slot_progress(slots: VictimRequirementSlots | None) -> bool:
    return slots is not None and any(getattr(slots, name) is not None for name in _SLOT_FIELDS)


def _stage_from_topic_key(topic_key: str) -> Optional[Stage]:
    """general_topic 키 접두어에서 계약 단계를 역산한다("전-①등기부등본_위험신호" → Stage.PRE).

    단계를 키에 담고 있는 건 general_topic 13개뿐이다. special_case 4종은 단계 축이 없고
    (신탁사기는 계약 전에도 후에도 발생한다), victim_interview/open_qa는 키 자체가 없다.
    그런 턴은 stage를 건드리지 않고 이전 턴 값을 그대로 둔다 — 모르는 값을 추측해 채우지 않는다.
    """
    try:
        return Stage(topic_key.split("-", 1)[0])
    except ValueError:
        return None


def _in_progress_route(state: DPartGraphState) -> str | None:
    """아직 종결되지 않은 victim_check 인터뷰가 진행 중이면 재분류 없이 그대로 이어간다.
    종결(victim_flow_closed)된 뒤에도 슬롯 값은 세션에 그대로 남으므로, 슬롯 진행 여부보다
    종결 플래그를 먼저 본다 — 안 그러면 인터뷰가 끝난 대화방의 모든 후속 턴이 영구히
    victim_check로 고정된다."""
    if state.get("victim_flow_closed"):
        return None
    if state.get("awaiting_relief_confirmation") or _has_slot_progress(state.get("victim_slots")):
        return "victim_check"
    return None


def _infer_special_case_from_topic(situation: SituationState) -> None:
    """인정받은 사용자의 topic이 특수상황 4종과 같은 상황을 가리키면 special_case를 채운다.

    전-③/전-⑤/전-⑥은 특수상황 4종과 같은 상황의 "인정 전" 판본이라(13개 항목 설명이 그렇게
    명시한다), 어느 쪽이냐는 recognized가 정한다. 그런데 모델은 이 겹치는 발화에서 special_case를
    채울지 말지 일관되지 않았다 — "피해자로 인정받았는데 다가구 선순위는 어떻게 확인하나요"에서
    같은 프롬프트로 5회 중 1~4회만 채웠다(실호출 측정). 프롬프트를 더 세게 밀면 반대로 상황이
    안 드러난 발화에도 4종을 지어냈다.

    그래서 모델에게 조르는 대신 규칙으로 정한다 — 겹침 관계는 도메인이 이미 고정해둔 사실이라
    매 턴 LLM에게 다시 물어볼 값이 아니다. 판정이 결정론적이 되고 테스트도 가능해진다.
    """
    if situation.recognized and not situation.special_case:
        situation.special_case = SITUATION_TOPIC_TO_SPECIAL_CASE.get(situation.topic)


def situation_from_supervisor_result(result: dict) -> SituationState:
    """call_supervisor의 tool 인자 dict를 상황모델로 변환한다.

    해당 없는 축은 키가 아예 빠져 오므로 .get()으로 읽는다. 어휘 검증은 SituationState가 한다.
    LLM 출력을 상황모델로 바꾸는 곳은 여기 하나여야 한다 — 호출부가 각자 SituationState를
    조립하면 정규화(_infer_special_case_from_topic)를 빠뜨린 채로도 그럴듯하게 동작한다.
    """
    situation = SituationState(
        recognized=result.get("recognized"),
        stage=result.get("stage"),
        risk_signals=result.get("risk_signals") or [],
        topic=result.get("topic"),
        special_case=result.get("special_case"),
    )
    _infer_special_case_from_topic(situation)
    return situation


def route(situation: SituationState) -> str:
    """상황모델에서 이번 턴 실행 노드를 파생시키는 순수함수.

    인터뷰 축(victim_check 진행 중)은 여기 없다 — 상황모델이 아니라 기존 플래그에서 파생되는
    값이라 run_supervisor가 앞단(_in_progress_route)에서 먼저 처리한다.

    특수상황 분기는 예전 프롬프트 문언("위험신호가 있고 + 인정된 상태")과 달리 위험신호를
    요구하지 않는다. 예전엔 그 조건을 LLM이 뭉뚱그려 판단했지만, 이제 risk_signals는 6종 enum에
    문자로 매칭된 결과라 "신탁을 걸어놨다" 같은 발화에선 빈 배열로 온다 — 옛/새 코드를 같은 발화로
    실호출 비교해 확인했다. 위험신호를 요구하면 인정받은 사용자가 특수상황을 말해도 자유질의로
    새어나간다. 애초에 이미 인정받은 사용자에게 위험신호 유무를 다시 묻는 건 의미가 없다.

    인정받았는데 특수 4종도 topic도 아닌 사용자는 recognized_general이 받는다. 예전엔 이들이
    제약 없는 자유질의(open_qa)로 떨어져 인지형 지원절차 개요를 못 받았다 — 납작한 카테고리
    구조라 코드에 드러나지 않던 빈칸이었다.

    인정받았어도 topic이 잡히면 general_scenario 그대로다. 13개 항목은 항목별 topic_tag로 조문·
    판례를 정조준해 검색하는데, 인지 여부를 이유로 recognized_general(전체 검색)로 보내면 애써
    판별한 topic 축을 버리게 된다. "인정받은 사람에게 예방 톤이 나온다"는 건 라우팅이 아니라
    프롬프트에서 다룰 문제다.
    """
    if situation.recognized:
        if situation.special_case:
            return "special_cases"
        if not situation.topic:
            return "recognized_general"
    elif situation.risk_signals:
        return "victim_check"
    if situation.topic:
        return "general_scenario"
    return "open_qa"


async def run_supervisor(state: DPartGraphState) -> DPartGraphState:
    """이번 턴 상황모델(situation)을 갱신하고 라우팅 대상(route_target)을 결정한다."""
    in_progress = _in_progress_route(state)
    if in_progress is not None:
        state["route_target"] = in_progress
        return state

    result = await llm_d_part.call_supervisor(get_active_query(state))
    situation = situation_from_supervisor_result(result)
    state["situation"] = situation
    target = route(situation)
    state["route_target"] = target

    if target == "special_cases":
        state["special_case_matched"] = situation.special_case
    elif target == "general_scenario":
        state["general_topic_matched"] = situation.topic
        derived_stage = _stage_from_topic_key(situation.topic)
        if derived_stage is not None:
            state["stage"] = derived_stage

    return state
