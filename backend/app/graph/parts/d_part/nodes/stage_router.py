"""
계약 단계(전/중/후) 1차 판별 노드.
판별 결과는 사용자에게 확인받는 단계를 거칩니다.
"""
from app.graph.parts.d_part.schemas import DPartGraphState, Stage

_CONFIRM_YES = ("네", "맞아요", "맞습니다", "응", "yes", "y", "맞음", "맞아")
_CONFIRM_NO = ("아니", "아니요", "아니에요", "틀렸", "no", "n")

_PRE_KEYWORDS = ("계약 전", "계약하려고", "계약서 작성", "이사 준비", "곧 계약", "계약 예정")
_DURING_KEYWORDS = ("살고 있", "거주 중", "지금 살", "거주하고")
_POST_KEYWORDS = ("이사 나갔", "퇴거", "계약 끝", "계약 종료", "만기", "이사했")


async def _mock_classify_stage(user_input: str) -> Stage:
    """실제 GPT-4o 연동 전까지 쓰는 키워드 기반 mock 분류기.
    app/llm/d_part.py의 실제 LLM 레이어가 준비되면 이 함수만 교체하면 된다."""
    if any(kw in user_input for kw in _POST_KEYWORDS):
        return Stage.POST
    if any(kw in user_input for kw in _DURING_KEYWORDS):
        return Stage.DURING
    if any(kw in user_input for kw in _PRE_KEYWORDS):
        return Stage.PRE
    return Stage.PRE  # 애매하면 가장 이른 단계(전)를 기본값으로— 확인 단계에서 어차피 되묻는다


def _confirmation_question(stage: Stage) -> str:
    return f"말씀하신 내용을 보면 '{stage.value}' 단계로 보입니다. 맞으신가요?"


async def route_stage(state: DPartGraphState) -> DPartGraphState:
    """전/중/후 1차 판별 + 사용자 확인 노드.

    risk_trigger(단위 11)와 독립적으로 동작 — 위험신호는 여기서 신경쓰지 않는다.
    상태기계:
      stage_confirmed=True          → no-op, 이전 턴 값 그대로 통과 (매 턴 재판별하지 않음)
      stage is None                 → mock 판별 후 확인 질문 세팅
      stage 있음 + stage_confirmed=False → 이번 턴 입력을 확인 응답(긍정/부정)으로 해석
    """
    if state.get("stage_confirmed"):
        return state

    user_input = state["user_input"]

    if state.get("stage") is None:
        stage = await _mock_classify_stage(user_input)
        state["stage"] = stage
        state["stage_confirmed"] = False
        state["final_answer"] = _confirmation_question(stage)
        return state

    if any(kw in user_input for kw in _CONFIRM_YES):
        state["stage_confirmed"] = True
        state["final_answer"] = None
    elif any(kw in user_input for kw in _CONFIRM_NO):
        state["stage"] = None
        state["stage_confirmed"] = False
        state["final_answer"] = "죄송합니다, 다시 한번 현재 상황을 말씀해 주시겠어요?"
    else:
        state["final_answer"] = _confirmation_question(state["stage"])

    return state
