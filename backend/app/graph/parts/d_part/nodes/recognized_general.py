"""
인지형 비특수 경로 — 이미 피해자로 인정받았으나 특수상황 4종에도, 13개 항목에도 걸리지 않은
사용자를 받는다.

예전엔 이들이 open_qa로 떨어졌다. 그래서 "사용자 상황을 알지 못한다"고 전제한 일반론 답변을
받았고, 인지형 지원절차 개요(special_cases가 붙여주는 것)도 못 받았다. 인정받았다는 사실이
발화에 뚜렷이 드러나 있는데도 그랬다 — 축이 카테고리 하나로 압축돼 있어 라우팅이 그 정보를
쓸 자리가 없었기 때문이다.

검색은 open_qa와 같다(topic_tag가 없으므로 전체 검색 — _open_search). 다른 건 두 가지다.
(a) 이미 지나간 시점이므로 예방이 아니라 대응·회복 관점으로 답하고(response_recognized_general.md),
(b) 지원절차 개요를 appendix로 붙인다 — special_cases(§8.4)와 대칭.
"""
from app.graph.parts.d_part.nodes._open_search import retrieve_open_context
from app.graph.parts.d_part.schemas import DPartGraphState
from app.llm import d_part as llm_d_part

# 지원절차 개요(대응 절차 사실) — special_cases._SPECIAL_CASE_GUIDANCE와 같은 자리(해설 뒤·면책
# 앞)에 붙는 같은 성격의 안내라, 절차 사실은 LLM 생성이 아니라 여기 하드코딩한다(종합문서 §14.1).
# 상황이 4종 중 무엇인지 특정되지 않은 경로이므로 특정 상황에만 열리는 수단(상속인·파산관재인
# 청구, 신탁원부 확인 등)은 담지 않고, 피해자 결정을 받았다면 공통으로 검토 대상인 것만 둔다.
# 이미 결정을 받은 사용자라 action_plan_data._APPLY_STEP(결정 신청 안내)도 해당하지 않는다.
# 문구/지원수단 적용요건은 검수 대상(기획서 §7). 면책은 finalize가 자동 첨부.
_RECOGNIZED_GUIDANCE = (
    "■ 대응\n"
    "- 피해자 결정에 따라 우선매수권, 경·공매 유예, 조세채권 안분, 최우선변제, 금융지원 등을 "
    "활용하실 수 있는지 관할 시·도와 확인하시길 권해드립니다.\n"
    "- 퇴거하시더라도 임차권등기명령으로 대항력·우선변제권을 유지하시길 권해드립니다.\n"
    "- 배당요구 종기 등 기한은 관할 법원·대한법률구조공단에서 확인하시길 권해드립니다."
)


async def handle_recognized_general(state: DPartGraphState) -> DPartGraphState:
    """전체 검색 + 인지형 관점 응답 스트림을 세팅하고 지원절차 개요를 appendix로 넘긴다."""
    context = await retrieve_open_context(state)
    if context is None:      # 근거 없음 — final_answer는 _open_search가 이미 확정했다
        return state

    state["answer_kind"] = "recognized_general"
    state["response_stream"] = llm_d_part.generate_response(context, "recognized_general")
    state["appendix_text"] = _RECOGNIZED_GUIDANCE   # finalize가 해설 뒤·면책 앞에 append
    return state
