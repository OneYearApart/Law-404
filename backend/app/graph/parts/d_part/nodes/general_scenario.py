"""
위험신호 미감지 시 전/중/후 단계별 일반 시나리오(전6/중5/후2=13개 항목) 응답 노드.
special_cases.py(키워드+LLM 매칭)와 response_assembly.py(RAG 검색+응답 생성)를 결합한 구조.
work-unit 17 — 노드 10~13(판별/라우팅)과 완전히 별개의 작업 범위(작업지시서 17번 참고).
"""
from app.graph.parts.d_part.schemas import DPartGraphState, Stage
from app.llm import d_part as llm_d_part
from app.rag.retrievers.d_part import DPartRetriever

_retriever = DPartRetriever()

# 키 문자열은 app/rag/ingestion/links_d.py::TOPIC_TAG_KEYWORDS와 동일 규칙 — 기존 9개 항목은
# 같은 값을 쓰고(있는 4개 항목만: 링크 모듈에 정의 없는 4개는 그래프 판별 전용으로 여기서 새로 정의,
# DB topic_tags 반영은 이번 범위 밖).
_GENERAL_TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "전-①등기부등본_위험신호": ("등기부등본", "말소기준권리"),
    "전-②전세가율_HUG보증보험": ("전세가율", "보증보험"),
    "전-③다가구_선순위보증금": ("다가구", "선순위 보증금", "선순위 임차인"),
    "전-④계약서_특약사항": ("특약", "특약사항"),
    "전-⑤신탁사기": ("신탁사", "신탁사기", "수탁자"),
    "전-⑥공인중개사_허위고지": ("공인중개사", "허위", "기망"),
    "중-①소유권_변동모니터링": ("소유권 변동", "소유자가 바뀌", "매매로 넘어가"),
    "중-②근저당_추가설정": ("근저당",),
    "중-③임대인_세금체납": ("세금체납", "체납", "압류"),
    "중-④갱신시점_위험": ("갱신료", "갱신 거절", "갱신 시점"),
    "중-⑤다가구_타세입자_피해": ("다른 세입자", "타 세입자", "이웃 세입자"),
    "후-①대항력_우선변제권_상실": ("대항력", "우선변제권"),
    "후-②이중계약_배당순위": ("배당금", "배당 순위", "배당순위", "이중계약"),
}

_TOPIC_LABELS: dict[str, str] = {
    "전-①등기부등본_위험신호": "등기부등본 위험 신호 해석(근저당, 가압류, 소유권 이전 이력)",
    "전-②전세가율_HUG보증보험": "전세가율/HUG 보증보험 가입 가능 여부 미확인",
    "전-③다가구_선순위보증금": "다가구주택 선순위 보증금 미확인",
    "전-④계약서_특약사항": "계약서 특약사항 위험 조항 해석",
    "전-⑤신탁사기": "임대인 실제 소유자 여부(신탁사기)",
    "전-⑥공인중개사_허위고지": "공인중개사 허위/누락 고지",
    "중-①소유권_변동모니터링": "소유권 변동 모니터링",
    "중-②근저당_추가설정": "근저당 추가 설정 모니터링",
    "중-③임대인_세금체납": "임대인 세금 체납 확인",
    "중-④갱신시점_위험": "갱신 시점 위험(갱신료 요구, 갱신 거절 빙자 사기)",
    "중-⑤다가구_타세입자_피해": "다가구주택 타 세입자 피해 소식(조기경보)",
    "후-①대항력_우선변제권_상실": "대항력/우선변제권 상실 위험",
    "후-②이중계약_배당순위": "이중계약/배당 순위 다툼",
}


def _stage_topics(stage: Stage) -> dict[str, tuple[str, ...]]:
    prefix = f"{stage.value}-"
    return {key: keywords for key, keywords in _GENERAL_TOPIC_KEYWORDS.items() if key.startswith(prefix)}


def _format_context(topic_key: str, retrieved: list) -> str:
    lines = [f"항목: {_TOPIC_LABELS[topic_key]}"]
    for chunk in retrieved:
        lines.append(f"[{chunk.source_type}] {chunk.content}")
    return "\n".join(lines)


async def _llm_topic_check(user_input: str, stage: Stage) -> str | None:
    """1단계 키워드 스캔이 못 잡은 애매한 케이스를 LLM으로 보완 판별한다(현재 단계 항목으로 한정)."""
    choices = list(_stage_topics(stage).keys())
    result = await llm_d_part.call_general_scenario(user_input, stage.value, choices)
    return result.get("category")


async def handle_general_scenario(state: DPartGraphState) -> DPartGraphState:
    """위험신호 미감지 + 진행 중인 판별 흐름 없음 상태에서 도달하는 일반 시나리오 노드.
    이미 final_answer가 세팅된 턴(예: stage_router 확인질문 대기 중)은 건드리지 않고 통과한다."""
    if state.get("final_answer") is not None:
        return state

    stage = state["stage"]
    user_input = state["user_input"]
    topic_key = None

    for key, keywords in _stage_topics(stage).items():
        if any(kw in user_input for kw in keywords):
            topic_key = key
            break

    if topic_key is None:
        topic_key = await _llm_topic_check(user_input, stage)

    if topic_key is None:
        state["general_topic_matched"] = None
        return state

    state["general_topic_matched"] = topic_key
    retrieved = await _retriever.search_by_topic(topic_key, _TOPIC_LABELS[topic_key])
    state["retrieved_chunks"] = retrieved["statute"] + retrieved["case_law"] + retrieved["cases"]

    context = _format_context(topic_key, state["retrieved_chunks"])
    state["response_stream"] = llm_d_part.generate_response(context)
    return state
