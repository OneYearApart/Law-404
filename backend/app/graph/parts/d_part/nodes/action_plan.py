"""
지원절차 액션플랜 노드 — victim_check가 이번 턴에 판정(높음/추가확인)을 새로 확정한 경우에만
결정론적 액션플랜 텍스트를 만들어 state["action_plan_text"]에 담는다. finalize가 스트림 말미에
면책 앞으로 첨부한다(_disclaimer와 동일한 결정론적 첨부 원칙 — 단위 30).

인지형 special_cases(§8.4)가 이미 인정받은 피해자에게 개요 수준 지원절차를 안내하는 것과 대칭으로,
'높음' 판정을 받은 미인지형 사용자에게 같은 개요 수준 안내를 제공한다(기획서 §1.1). 절차 사실은
LLM 생성이 아니라 action_plan_data.py 큐레이션 상수에서만 조립한다(종합문서 §14.1).
"""
from app.graph.parts.d_part.nodes import action_plan_data as data
from app.graph.parts.d_part.schemas import DPartGraphState, VictimJudgment, VictimRequirementSlots


def build_action_plan(judgment: VictimJudgment, slots: VictimRequirementSlots) -> str:
    """판정 + 슬롯 상태로 액션플랜 텍스트를 결정론적으로 조립한다.
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


async def attach_action_plan(state: DPartGraphState) -> DPartGraphState:
    """victim_check가 이번 턴에 판정을 새로 확정한 경우(needs_response_assembly)에만 액션플랜을
    조립한다. 그 외 모든 경로(special_cases/general_scenario/open_qa/스테이지 확인질문/구제수단
    제외/fallback)는 needs_response_assembly가 falsy이므로 no-op으로 통과 → action_plan_text 미설정
    → finalize가 액션플랜을 붙이지 않는다(기존 동작 유지).
    """
    if not state.get("needs_response_assembly"):
        return state
    judgment = state.get("victim_judgment")
    if judgment is None:
        return state
    state["action_plan_text"] = build_action_plan(judgment, state["victim_slots"])
    return state
