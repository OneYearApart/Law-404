"""
D파트 LangGraph 서브그래프.

흐름:
1. supervisor — 위험신호+인지여부+특수상황4종+일반13개+open_qa를 LLM tool calling
   1회로 한 번에 분류(2026-07-14 리팩터링: 예전 risk_trigger/recognition_router 두
   노드와 special_cases/general_scenario의 매칭부를 여기로 통합 — 각 노드가 자기
   카테고리만 아는 좁은 시야로 판단하다 보니 "13개 항목 밖 질문은 무조건 fallthrough"
   같은 사각지대가 생겼던 문제를 없애기 위함). 계약 단계(전/중/후)는 이 분류 결과에서
   파생시킨다 — 2026-07-16 이전까지는 stage_router 노드가 앞단에서 별도 LLM 호출로
   판별하고 사용자 확인까지 받았으나, 7/14 리팩터링 이후 그 stage 값을 읽는 노드가
   하나도 없어 비용과 첫 턴만 소모했다(단위 29). 같은 정보가 카테고리 키 접두어에
   이미 더 정확하게 들어있다.
2. victim_check — 미인지형 판별(전세사기피해자법 요건 슬롯 매핑)
3. special_cases — 인지형 특수상황 4종 안내(카테고리는 supervisor가 이미 정함)
4. general_scenario — 일반 시나리오 13개 항목 중 매칭된 항목의 원문→해설→상황적용
   응답 조립(카테고리는 supervisor가 이미 정함, 계약단계 무관하게 전체 13개가 대상)
5. recognized_general — 인정받았으나 특수 4종에도 13개 항목에도 안 걸리는 피해자.
   검색은 open_qa와 같지만(topic_tag 없음) 대응·회복 관점으로 답하고 지원절차 개요를 첨부한다
6. open_qa — 위 어디에도 해당하지 않는 질문에 대한 제약 없는 RAG 검색+응답 생성
7. response_assembly — victim_check가 방금 판단을 확정한 턴에만 원문→해설→상황적용 조립
8. action_plan — 그 판정 확정 턴에만 개요 수준 지원절차 안내를 조립(finalize가 면책 앞에 첨부).
   그 외 경로는 no-op 통과 — 인지형 special_cases(§8.4)와 미인지형 판정 경로를 대칭화(기획서 §1.1)
9. finalize — 나머지 모든 턴(이미 완결된 final_answer)을 SSE 스트림 형태로 통일

판단 단계(1~5)는 .ainvoke()로 동기 실행하고, 최종 답변 생성부터만 스트리밍합니다.
"""
from langgraph.graph import StateGraph

from app.graph.parts.d_part.nodes.action_plan import attach_action_plan
from app.graph.parts.d_part.nodes.finalize import finalize_response
from app.graph.parts.d_part.nodes.general_scenario import handle_general_scenario
from app.graph.parts.d_part.nodes.open_qa import handle_open_qa
from app.graph.parts.d_part.nodes.recognized_general import handle_recognized_general
from app.graph.parts.d_part.nodes.response_assembly import assemble_response
from app.graph.parts.d_part.nodes.special_cases import match_special_case
from app.graph.parts.d_part.nodes.supervisor import run_supervisor
from app.graph.parts.d_part.nodes.victim_check import check_victim_status
from app.graph.parts.d_part.schemas import DPartGraphState


def _route_after_supervisor(state: DPartGraphState) -> str:
    return state["route_target"]


builder = StateGraph(DPartGraphState)
builder.add_node("supervisor", run_supervisor)
builder.add_node("victim_check", check_victim_status)
builder.add_node("special_cases", match_special_case)
builder.add_node("general_scenario", handle_general_scenario)
builder.add_node("recognized_general", handle_recognized_general)
builder.add_node("open_qa", handle_open_qa)
builder.add_node("response_assembly", assemble_response)
builder.add_node("action_plan", attach_action_plan)
builder.add_node("finalize", finalize_response)

builder.set_entry_point("supervisor")
builder.add_conditional_edges(
    "supervisor",
    _route_after_supervisor,
    {
        "victim_check": "victim_check",
        "special_cases": "special_cases",
        "general_scenario": "general_scenario",
        "recognized_general": "recognized_general",
        "open_qa": "open_qa",
    },
)
builder.add_edge("victim_check", "response_assembly")
builder.add_edge("special_cases", "finalize")
builder.add_edge("general_scenario", "finalize")
builder.add_edge("recognized_general", "finalize")
builder.add_edge("open_qa", "finalize")
builder.add_edge("response_assembly", "action_plan")
builder.add_edge("action_plan", "finalize")
builder.set_finish_point("finalize")

graph = builder.compile()
