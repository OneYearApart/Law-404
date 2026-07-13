"""
계약 단계(전/중/후) 1차 판별 노드.
판별 결과는 사용자에게 확인받는 단계를 거칩니다.
"""
from app.graph.parts.d_part.schemas import DPartGraphState, Stage
from app.llm import d_part as llm_d_part

_CONFIRM_YES = ("네", "맞아요", "맞습니다", "응", "yes", "y", "맞음", "맞아")
_CONFIRM_NO = ("아니", "아니요", "아니에요", "틀렸", "no", "n")


async def _classify_stage(user_input: str) -> Stage:
    result = await llm_d_part.call_stage_router(user_input)
    return Stage(result["stage"])


def _confirmation_question(stage: Stage) -> str:
    return f"말씀하신 내용을 보면 '{stage.value}' 단계로 보입니다. 맞으신가요?"


async def route_stage(state: DPartGraphState) -> DPartGraphState:
    """전/중/후 1차 판별 + 사용자 확인 노드.

    risk_trigger(단위 11)와 독립적으로 동작 — 위험신호는 여기서 신경쓰지 않는다.
    상태기계:
      stage_confirmed=True          → no-op, 이전 턴 값 그대로 통과 (매 턴 재판별하지 않음)
      stage is None                 → LLM 판별 후 확인 질문 세팅
      stage 있음 + stage_confirmed=False → 이번 턴 입력을 확인 응답(긍정/부정)으로 해석
    """
    user_input = state["user_input"]

    if state.get("stage_confirmed"):
        state["active_query"] = user_input
        return state

    if state.get("stage") is None:
        stage = await _classify_stage(user_input)
        state["stage"] = stage
        state["stage_confirmed"] = False
        state["final_answer"] = _confirmation_question(stage)
        state["active_query"] = user_input
        return state

    if any(kw in user_input for kw in _CONFIRM_YES):
        state["stage_confirmed"] = True
        state["final_answer"] = None
        # active_query는 건드리지 않는다 — 지난 턴에 스택해둔 실질 질문을
        # 이번 턴의 "네" 답변으로 덮어쓰면 안 된다 (핵심 버그 수정 지점)
    elif any(kw in user_input for kw in _CONFIRM_NO):
        state["stage"] = None
        state["stage_confirmed"] = False
        state["final_answer"] = "죄송합니다, 다시 한번 현재 상황을 말씀해 주시겠어요?"
        state["active_query"] = None
    else:
        state["final_answer"] = _confirmation_question(state["stage"])

    return state
