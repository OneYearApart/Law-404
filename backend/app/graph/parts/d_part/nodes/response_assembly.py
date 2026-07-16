"""
victim_check 최종판단(victim_judgment) 도출 시점에만 실행되는 응답 조립 노드.
team 공통 app/graph/agents/response_agent.py가 아직 미구현(파트 공통 work-unit 14)이라
D파트 자체 구현으로 우회 — 통합 시 팀과 공유 필요(2026-07-11 확정).
다른 종결 경로(special_cases/victim_fallback/스테이지 확인질문 등)는 이미 완결된
final_answer를 갖고 있어 이 노드를 거치지 않고 finalize.py에서 바로 스트림으로 감싼다.

주의: LangGraph의 ainvoke() 반환값은 각 노드가 받은 state와 동일 객체가 아니다
(내부적으로 다시 조립됨) — 그래서 response_stream을 소진한 뒤 state를 사후 변경해도
호출부(ainvoke 반환값)에는 반영되지 않는다. 이 노드는 final_answer를 일부러 None으로
남겨두고, 실제 전체 텍스트 조립은 스트림을 직접 소비하는 호출부(routes/d_part.py)가
청크를 모아서 처리한다.
"""
from app.graph.parts.d_part.nodes._context import format_chunks
from app.graph.parts.d_part.schemas import DPartGraphState, get_active_query
from app.llm import d_part as llm_d_part
from app.rag.retrievers.d_part import DPartRetriever

_retriever = DPartRetriever()


def _format_context(state: DPartGraphState) -> str:
    slots = state["victim_slots"]
    judgment = state["victim_judgment"]
    retrieved = state.get("retrieved_chunks", [])
    header = f"판단 결과: {judgment.value}\n요건 슬롯: {slots.model_dump(mode='json')}"
    return f"{header}\n\n{format_chunks(retrieved)}"


async def assemble_response(state: DPartGraphState) -> DPartGraphState:
    """victim_check가 이번 턴에 판단을 새로 확정했을 때만(needs_response_assembly) 조립한다.
    victim_judgment는 세션에 영속되는 값이라 그것만 보고 조립하면, 판정이 끝난 대화방의
    모든 후속 턴이 같은 판정 응답을 RAG+LLM으로 매번 재생성하게 된다."""
    if not state.get("needs_response_assembly"):
        return state

    retrieved = await _retriever.search_by_requirement(
        state["victim_slots"], situation_query=get_active_query(state)
    )
    state["retrieved_chunks"] = (retrieved["statute"] + retrieved["case_law"]
                                 + retrieved["cases"] + retrieved.get("guides", []))

    context = _format_context(state)
    state["response_stream"] = llm_d_part.generate_response(context)
    return state
