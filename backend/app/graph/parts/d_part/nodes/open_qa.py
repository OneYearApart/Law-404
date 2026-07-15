"""
supervisor가 어디에도 매칭시키지 못한 질문(open_qa)을 위한 폴백 경로.
13개 일반 시나리오 항목이나 특수상황처럼 미리 정해진 topic_tag가 없으므로,
전체 임베딩 테이블에서 제약 없는 top-k 벡터검색을 1회만 수행한다(재검색 없음 —
검색 결과가 빈약하면 응답 생성 프롬프트가 알아서 "관련 정보를 찾기 어렵다"는
식으로 안내하도록 둔다. ReAct식 반복검색은 턴당 LLM 호출·지연시간이 늘어나는
데 비해 이 도메인에서 실익이 적다고 판단해 의도적으로 도입하지 않음).
"""
from app.graph.parts.d_part.nodes._context import format_chunks
from app.graph.parts.d_part.schemas import DPartGraphState, get_active_query
from app.llm import d_part as llm_d_part
from app.rag.retrievers.d_part import DPartRetriever

_retriever = DPartRetriever()


async def handle_open_qa(state: DPartGraphState) -> DPartGraphState:
    query = get_active_query(state)
    chunks = await _retriever.search(query, top_k=5)
    state["retrieved_chunks"] = chunks

    context = format_chunks(chunks)
    state["response_stream"] = llm_d_part.generate_response(context)
    return state
