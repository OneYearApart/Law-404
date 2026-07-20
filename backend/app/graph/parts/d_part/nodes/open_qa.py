"""
supervisor가 어디에도 매칭시키지 못한 질문(open_qa)을 위한 폴백 경로.
13개 일반 시나리오 항목이나 특수상황처럼 미리 정해진 topic_tag가 없으므로 전체 검색으로
빠진다 — 검색과 '근거 없음' 규칙은 같은 처지인 recognized_general과 공유한다(_open_search).
ReAct식 반복검색은 턴당 비용/지연 대비 실익이 적다고 판단해 여전히 도입하지 않는다(단일 검색).

같은 전체 검색을 쓰더라도 인정받은 사용자는 recognized_general이 받는다 — 이 경로는 사용자
상황을 전혀 모르는 일반론 응답이다(prompts/response_open_qa.md).
"""
from app.graph.parts.d_part.nodes._open_search import retrieve_open_context
from app.graph.parts.d_part.schemas import DPartGraphState
from app.llm import d_part as llm_d_part


async def handle_open_qa(state: DPartGraphState) -> DPartGraphState:
    context = await retrieve_open_context(state)
    if context is None:      # 근거 없음 — final_answer는 _open_search가 이미 확정했다
        return state

    state["answer_kind"] = "open_qa"
    state["response_stream"] = llm_d_part.generate_response(context, "open_qa")
    return state
