"""
인지형 비특수 경로 — 이미 피해자로 인정받았으나 특수상황 4종에도, 13개 항목에도 걸리지 않은
사용자를 받는다.

예전엔 이들이 open_qa로 떨어졌다. 그래서 "사용자 상황을 알지 못한다"고 전제한 일반론 답변을
받았고, 인지형 지원절차 개요(special_cases가 붙여주던 것)도 못 받았다. 인정받았다는 사실이
발화에 뚜렷이 드러나 있는데도 그랬다 — 축이 카테고리 하나로 압축돼 있어 라우팅이 그 정보를
쓸 자리가 없었기 때문이다.

검색은 open_qa와 같다(topic_tag가 없으므로 전체 검색 — _open_search). 다른 건 이미 지나간
시점이므로 예방이 아니라 대응·회복 관점으로 답한다는 것뿐이다(response_recognized_general.md).
지원절차 개요는 이 노드가 아니라 support_appendix가 상황을 보고 붙인다(D3).
"""
from app.graph.parts.d_part.nodes._open_search import retrieve_open_context
from app.graph.parts.d_part.schemas import DPartGraphState
from app.llm import d_part as llm_d_part


async def handle_recognized_general(state: DPartGraphState) -> DPartGraphState:
    """전체 검색 + 인지형 관점 응답 스트림을 세팅한다."""
    context = await retrieve_open_context(state)
    if context is None:      # 근거 없음 — final_answer는 _open_search가 이미 확정했다
        return state

    state["answer_kind"] = "recognized_general"
    state["response_stream"] = llm_d_part.generate_response(context, "recognized_general")
    return state
