"""
D파트 LangGraph 서브그래프.

흐름:
1. supervisor — 상황의 축(인지여부·위험신호·특수상황4종·일반13개)을 LLM tool calling
   1회로 한 번에 판별해 situation에 담는다(2026-07-14 리팩터링: 예전 risk_trigger/
   recognition_router 두 노드와 special_cases/general_scenario의 매칭부를 여기로 통합 —
   각 노드가 자기 카테고리만 아는 좁은 시야로 판단하다 보니 "13개 항목 밖 질문은 무조건
   fallthrough" 같은 사각지대가 생겼던 문제를 없애기 위함).
   라우팅은 이 상황모델에서 순수함수로 파생시킨다(supervisor.route) — 저장하지 않는다.
   계약 단계(전/중/후)는 축으로 두지 않는다: stage_router 노드를 앞단에 두고 LLM 호출로
   판별하다 아무도 안 읽어 삭제했고(단위 29), supervisor 축으로 옮겨 담아봐도 마찬가지로
   읽는 곳이 없어 매 턴 판별 비용만 썼다(D1). 필요한 정보는 topic 키 접두어에 이미 있다.
2. victim_check — 미인지형 판별(전세사기피해자법 요건 슬롯 매핑)
3. special_cases — 인지형 특수상황 4종 해설(카테고리는 supervisor가 이미 정함)
4. general_scenario — 일반 시나리오 13개 항목 중 매칭된 항목의 원문→해설→상황적용
   응답 조립(항목은 supervisor가 이미 정함, 발화의 계약단계 무관하게 전체 13개가 대상)
5. recognized_general — 인정받았으나 특수 4종에도 13개 항목에도 안 걸리는 피해자.
   검색은 open_qa와 같지만(topic_tag 없음) 대응·회복 관점으로 답한다
6. open_qa — 위 어디에도 해당하지 않는 질문에 대한 제약 없는 RAG 검색+응답 생성
7. response_assembly — victim_check가 방금 판단을 확정한 턴에만 원문→해설→상황적용 조립
8. support_appendix — 응답 경로 전부가 지나는 지원절차 안내 부착점. 붙일지·무엇을 붙일지를
   상황모델+판정이 정한다(기획서 §1.1의 인지형/미인지형 대칭을 상태로 표현). 예전엔 이 판단이
   special_cases inline과 action_plan 노드로 갈라져 실행 경로에 묶여 있었다(D3)
9. finalize — 면책 첨부 + 나머지 모든 턴(이미 완결된 final_answer)을 SSE 스트림 형태로 통일

판단 단계(1~7)는 .ainvoke()로 동기 실행하고, 최종 답변 생성부터만 스트리밍합니다.
"""
from langgraph.graph import StateGraph

from app.graph.parts.d_part.nodes.finalize import finalize_response
from app.graph.parts.d_part.nodes.general_scenario import handle_general_scenario
from app.graph.parts.d_part.nodes.open_qa import handle_open_qa
from app.graph.parts.d_part.nodes.recognized_general import handle_recognized_general
from app.graph.parts.d_part.nodes.response_assembly import assemble_response
from app.graph.parts.d_part.nodes.special_cases import match_special_case
from app.graph.parts.d_part.nodes.support_appendix import attach_support_appendix
from app.graph.parts.d_part.nodes.supervisor import interview_in_progress, route, run_supervisor
from app.graph.parts.d_part.nodes.victim_check import check_victim_status
from app.graph.parts.d_part.schemas import DPartGraphState


def _route_after_supervisor(state: DPartGraphState) -> str:
    """이번 턴 실행 노드를 상황모델에서 파생시킨다 — supervisor가 state에 써둔 값을 읽지 않는다.
    파생되는 값을 저장하면 상황모델과 라우팅 대상이라는 진실원천이 둘로 갈라진다.

    인터뷰 진행 중이면 상황모델을 보지 않는다 — 이번 턴 발화가 슬롯 질문에 대한 답이라
    supervisor가 재분류를 건너뛰었고, situation엔 직전 턴 값이 남아 있다.
    """
    if interview_in_progress(state):
        return "victim_check"
    situation = state.get("situation")
    return route(situation) if situation is not None else "open_qa"


builder = StateGraph(DPartGraphState)
builder.add_node("supervisor", run_supervisor)
builder.add_node("victim_check", check_victim_status)
builder.add_node("special_cases", match_special_case)
builder.add_node("general_scenario", handle_general_scenario)
builder.add_node("recognized_general", handle_recognized_general)
builder.add_node("open_qa", handle_open_qa)
builder.add_node("response_assembly", assemble_response)
builder.add_node("support_appendix", attach_support_appendix)
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
# 모든 응답 경로가 부착점을 지난다 — 지원절차를 붙일지는 어느 노드가 실행됐는지가 아니라
# 상황이 정하므로(D3), 경로별로 갈라 놓으면 그 판단이 다시 실행 경로에 묶인다.
builder.add_edge("special_cases", "support_appendix")
builder.add_edge("general_scenario", "support_appendix")
builder.add_edge("recognized_general", "support_appendix")
builder.add_edge("open_qa", "support_appendix")
builder.add_edge("response_assembly", "support_appendix")
builder.add_edge("support_appendix", "finalize")
builder.set_finish_point("finalize")

graph = builder.compile()
