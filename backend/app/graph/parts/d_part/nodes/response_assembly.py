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
from app.graph.parts.d_part.nodes._context import build_context
from app.graph.parts.d_part.schemas import (
    VICTIM_SLOT_LABELS,
    DPartGraphState,
    SlotStatus,
)
from app.llm import d_part as llm_d_part
from app.rag.retrievers.d_part import DPartRetriever

_retriever = DPartRetriever()


_SLOT_STATUS_LABELS = {
    SlotStatus.FILLED: "충족",
    SlotStatus.UNFILLED: "미충족",
    SlotStatus.UNCLEAR: "확인되지 않음",
}


def _format_context(state: DPartGraphState) -> str:
    """LLM에 넘길 컨텍스트. 슬롯을 model_dump로 통째로 넘기면 모델이 영문 필드명을 그대로
    답변에 옮겨 적으므로(사용자에게 내부 변수명 노출) 사람이 읽는 문장으로 편다.

    ①~④ 요건만 싣는다 — auction_completed(①③ 면제 플래그)와 has_relief_measure(제외 사유)는
    요건이 아니라 통제 플래그라(schemas.py 주석) 함께 던지면 모델이 "has_relief_measure 요건이
    충족되지 않았습니다"처럼 쓴다. 구제수단이 없다는 건 오히려 지원 대상이라는 뜻인데 정반대로
    읽히므로, 요건과 성격이 다른 값은 아예 노출하지 않는다.
    """
    slots = state["victim_slots"]
    judgment = state["victim_judgment"]
    retrieved = state.get("retrieved_chunks", [])
    lines = [
        f"- {label}: {_SLOT_STATUS_LABELS.get(getattr(slots, name), '확인되지 않음')}"
        for name, label in VICTIM_SLOT_LABELS.items()
    ]
    header = f"판단 결과: {judgment.value}\n요건 충족 현황:\n" + "\n".join(lines)
    # 다른 경로와 달리 발화(query)를 넣지 않는다 — 이 턴의 발화는 슬롯 질문에 대한 답
    # ("아니요 없어요")이라 질문이 아니고, 그 내용은 이미 위 요건 충족 현황에 반영돼 있다.
    return build_context(retrieved, header=header)


async def assemble_response(state: DPartGraphState) -> DPartGraphState:
    """victim_check가 이번 턴에 판단을 새로 확정했을 때만(needs_response_assembly) 조립한다.
    victim_judgment는 세션에 영속되는 값이라 그것만 보고 조립하면, 판정이 끝난 대화방의
    모든 후속 턴이 같은 판정 응답을 RAG+LLM으로 매번 재생성하게 된다."""
    if not state.get("needs_response_assembly"):
        return state

    retrieved = await _retriever.search_by_requirement(
        state["victim_slots"], situation_query=state["user_input"]
    )
    state["retrieved_chunks"] = (retrieved["statute"] + retrieved["case_law"]
                                 + retrieved["cases"] + retrieved.get("guides", []))

    context = _format_context(state)
    state["answer_kind"] = "judgment"
    state["response_stream"] = llm_d_part.generate_response(context, "judgment")
    return state
