"""
D파트 LangGraph 서브그래프.

흐름:
1. stage_router — 전/중/후 1차 판별
2. risk_trigger — 위험신호 감지 (단계 횡단, 신호 있으면 인지/미인지 판별로 즉시 라우팅)
3. recognition_router — (트리거 감지 + 백지 상태일 때만) 인지형/미인지형 판별
4. victim_check — 미인지형 판별 (전세사기피해자법 요건 슬롯 매핑)
5. special_cases — 인지형 특수상황 매칭
6. general_scenario — 위험신호 없고 진행 중인 흐름도 없을 때, 전/중/후 13개 항목 중 매칭되는
   항목의 원문→해설→상황적용 응답 조립 (work-unit 17)
7. response_assembly — victim_check가 방금 판단을 확정한 턴에만 원문→해설→상황적용 조립
8. finalize — 나머지 모든 턴(이미 완결된 final_answer)을 SSE 스트림 형태로 통일

판단 단계(1~6)는 .ainvoke()로 동기 실행하고, 최종 답변 생성부터만 스트리밍합니다.
"""
from langgraph.graph import StateGraph

from app.graph.parts.d_part.nodes.finalize import finalize_response
from app.graph.parts.d_part.nodes.general_scenario import handle_general_scenario
from app.graph.parts.d_part.nodes.recognition_router import route_recognition
from app.graph.parts.d_part.nodes.response_assembly import assemble_response
from app.graph.parts.d_part.nodes.risk_trigger import detect_risk_signal
from app.graph.parts.d_part.nodes.special_cases import match_special_case
from app.graph.parts.d_part.nodes.stage_router import route_stage
from app.graph.parts.d_part.nodes.victim_check import check_victim_status
from app.graph.parts.d_part.schemas import DPartGraphState, VictimRequirementSlots

_SLOT_FIELDS = ("moved_in_and_fixed_date", "deposit_under_limit", "multiple_victims", "no_intent_to_return")


def _has_slot_progress(slots: VictimRequirementSlots | None) -> bool:
    return slots is not None and any(getattr(slots, name) is not None for name in _SLOT_FIELDS)


def _route_after_risk_trigger(state: DPartGraphState) -> str:
    """이미 진행 중인 흐름(특수상황 매칭됨/요건판정 진행 중)이면 이번 턴 재트리거 여부와
    무관하게 그 흐름을 계속 이어간다 — risk_trigger_detected는 매 턴 새로 계산되므로
    후속 턴(예: 구제수단 질문에 대한 답변)에선 다시 트리거되지 않는 게 정상이기 때문."""
    if state.get("special_case_matched") is not None:
        return "special_cases"
    if (
        state.get("victim_judgment") is not None
        or state.get("victim_fallback")
        or state.get("awaiting_relief_confirmation")
        or _has_slot_progress(state.get("victim_slots"))
    ):
        return "victim_check"
    if state.get("risk_trigger_detected"):
        return "recognition_router"
    return "general_scenario"


def _route_after_recognition(state: DPartGraphState) -> str:
    return "special_cases" if state.get("recognized") else "victim_check"


builder = StateGraph(DPartGraphState)
builder.add_node("stage_router", route_stage)
builder.add_node("risk_trigger", detect_risk_signal)
builder.add_node("recognition_router", route_recognition)
builder.add_node("victim_check", check_victim_status)
builder.add_node("special_cases", match_special_case)
builder.add_node("general_scenario", handle_general_scenario)
builder.add_node("response_assembly", assemble_response)
builder.add_node("finalize", finalize_response)

builder.set_entry_point("stage_router")
builder.add_edge("stage_router", "risk_trigger")
builder.add_conditional_edges(
    "risk_trigger",
    _route_after_risk_trigger,
    {
        "recognition_router": "recognition_router",
        "victim_check": "victim_check",
        "special_cases": "special_cases",
        "general_scenario": "general_scenario",
    },
)
builder.add_conditional_edges(
    "recognition_router",
    _route_after_recognition,
    {"victim_check": "victim_check", "special_cases": "special_cases"},
)
builder.add_edge("victim_check", "response_assembly")
builder.add_edge("special_cases", "finalize")
builder.add_edge("general_scenario", "finalize")
builder.add_edge("response_assembly", "finalize")
builder.set_finish_point("finalize")

graph = builder.compile()
