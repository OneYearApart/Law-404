"""
분류 supervisor 노드 — 예전 risk_trigger/recognition_router/special_cases와
general_scenario의 매칭부를 흡수해 카테고리 판단을 한 곳으로 모은 노드.

아직 종결되지 않은 victim_check 인터뷰(슬롯 채우는 중 / 구제수단 확인 대기)가 있으면
재분류 없이 그대로 이어간다. special_case_matched는 여기서 우선순위 대상으로 보지
않는다 — special_cases는 후속 대화가 없는 1회성 안내라, victim_check 슬롯 인터뷰처럼
"이번 턴 발화 자체가 분류 불가능한 답변"이 되는 경우가 없다. 오히려 재분류를 막으면 안내
이후 사용자가 말을 이어갈 때마다 매번 예전 안내문으로만 되돌아가게 된다.

분류가 필요한 턴은 LLM tool calling 1회로 위험신호+인지여부+특수상황4종+일반13개+open_qa를
한 번에 판별한다(call_supervisor). 카테고리별로 다음 노드를 결정하고, special_case/general_topic
카테고리는 그 실행 노드가 바로 조회할 수 있도록 special_case_matched/general_topic_matched에
값을 채워 넘긴다.
"""
from app.graph.parts.d_part.schemas import DPartGraphState, VictimRequirementSlots, get_active_query
from app.llm import d_part as llm_d_part

_SLOT_FIELDS = ("moved_in_and_fixed_date", "deposit_under_limit", "multiple_victims", "no_intent_to_return")


def _has_slot_progress(slots: VictimRequirementSlots | None) -> bool:
    return slots is not None and any(getattr(slots, name) is not None for name in _SLOT_FIELDS)


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


async def run_supervisor(state: DPartGraphState) -> DPartGraphState:
    """이번 턴 라우팅 대상(route_target)을 결정한다. stage_router 확인 게이트 대기 중
    (final_answer가 이미 세팅된 턴)이면 LLM 호출 없이 그대로 통과한다."""
    if state.get("final_answer") is not None:
        return state

    in_progress = _in_progress_route(state)
    if in_progress is not None:
        state["route_target"] = in_progress
        return state

    result = await llm_d_part.call_supervisor(get_active_query(state))
    category = result["category"]

    if category == "victim_interview":
        state["route_target"] = "victim_check"
    elif category.startswith("special_case:"):
        state["special_case_matched"] = category.removeprefix("special_case:")
        state["route_target"] = "special_cases"
    elif category.startswith("general_topic:"):
        state["general_topic_matched"] = category.removeprefix("general_topic:")
        state["route_target"] = "general_scenario"
    else:
        state["route_target"] = "open_qa"

    return state
