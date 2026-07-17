"""
지원절차 안내 부착의 단일 결정 지점 — "이 사용자에게 지원절차를 보여줄지"를 상황이 정한다.

예전엔 이 판단이 두 곳으로 갈라져 있었다. special_cases는 자기 노드가 실행됐다는 이유로
_SPECIAL_CASE_GUIDANCE를 inline으로 세팅했고, action_plan은 needs_response_assembly라는
다른 게이트에 배선돼 있었다. 서로 다른 게이트에 묶인 평행 메커니즘이라, 정작 "지원절차를
받아야 하는가"는 상황 질문인데도 라우팅이 바뀌면 안내가 부작용처럼 나타났다 사라졌다(D3).

이제 모든 응답 경로가 이 노드를 지나며, 부착 여부와 내용 모두 SituationState+판정이 정한다.
절차 사실 자체는 LLM 생성이 아니라 support_data.py 큐레이션 상수에서만 조립한다(§14.1).
결정은 그래프 안에서 끝내고 결과만 appendix_text 슬롯으로 넘긴다 — 실제 조립부
(routes/d_part.py)가 상황모델을 다시 해석하면 진실원천이 둘이 된다.
"""
from typing import Optional

from app.graph.parts.d_part.nodes import support_data as data
from app.graph.parts.d_part.schemas import (
    DPartGraphState,
    SituationState,
    VictimJudgment,
    VictimRequirementSlots,
)


def build_action_plan(judgment: VictimJudgment, slots: VictimRequirementSlots) -> str:
    """판정 + 슬롯 상태로 미인지형 액션플랜 텍스트를 결정론적으로 조립한다.
    '있음'(PRESENT)은 현재 victim_check가 산출하지 않으므로(§8.5 범위 밖) 높음과 동일 처리한다.
    """
    sections: list[str] = []

    if judgment == VictimJudgment.NEEDS_CONFIRMATION:
        gap_lines = data.unfilled_slot_lines(slots)
        body = "\n".join(gap_lines) if gap_lines else "- 추가로 확인이 필요한 요건이 있습니다."
        sections.append(f"{data._CONFIRM_HEADER}\n{body}")
    else:  # 높음(또는 향후 있음)
        measures = (
            data._SUPPORT_MEASURES_POST_AUCTION
            if slots.auction_completed
            else data._SUPPORT_MEASURES_PRE_AUCTION
        )
        sections.append(f"{data._APPLY_STEP}\n{measures}")

    sections.append(data._PROTECTIVE_STEPS)   # 공통 보호조치
    sections.append(data._CONTACTS)           # 공통 상담 안내
    return "\n\n".join(sections)


def build_support_appendix(
    situation: Optional[SituationState],
    newly_judged: bool,
    judgment: Optional[VictimJudgment],
    slots: VictimRequirementSlots,
) -> Optional[str]:
    """붙일 지원절차 안내를 고른다. 붙일 이유가 없으면 None.

    미인지형 판정을 먼저 본다. 판정은 이번 턴에 새로 확정된 것(newly_judged)만 인정한다 —
    victim_judgment는 carryover라 그것만 보면 판정 이후 모든 턴에 액션플랜이 재부착된다.
    situation은 인터뷰 진행 턴에 재분류를 건너뛰므로(supervisor._in_progress_route) 직전 턴 값이
    남아 있을 수 있어, 이번 턴 확정 사실인 판정을 먼저 놓는 편이 안전하다.

    인지형은 상황이 특정됐으면 그 상황의 안내를, 아니면 인정 피해자 공통 안내를 붙인다.
    어느 노드가 답변을 만들었는지는 보지 않는다 — 인정받은 사용자는 13개 항목을 물었든
    상황을 밝혔든 같은 근거로 같은 안내를 받아야 한다(그게 D3의 요지다).
    """
    if newly_judged and judgment is not None:
        return build_action_plan(judgment, slots)
    if situation is not None and situation.recognized:
        if situation.special_case:
            return data._SPECIAL_CASE_GUIDANCE[situation.special_case]
        return data._RECOGNIZED_GUIDANCE
    return None


async def attach_support_appendix(state: DPartGraphState) -> DPartGraphState:
    """모든 응답 경로가 지나는 부착점. 붙일 게 없는 턴은 no-op으로 통과한다."""
    # 고정 텍스트 턴(확인질문/fallback/'근거 없음')은 finalize가 appendix_text를 읽지 않는다
    # — 첨부는 스트림 경로 전용이다. 여기서 세팅해봐야 사용자에게 닿지 않으므로 아예 판단하지 않는다.
    if state.get("response_stream") is None:
        return state

    appendix = build_support_appendix(
        state.get("situation"),
        bool(state.get("needs_response_assembly")),
        state.get("victim_judgment"),
        state.get("victim_slots") or VictimRequirementSlots(),
    )
    if appendix is not None:
        state["appendix_text"] = appendix
    return state
