"""
위험신호 감지 시 미인지형(victim_check)/인지형(special_cases) 중 어디로 보낼지
판별하는 라우팅 전용 노드. 요건 슬롯 판정이나 특수상황 매칭 자체는 하지 않고,
"사용자가 이미 자신이 법적으로 피해자로 인정받았다고 말하고 있는지"만 이진 판별한다.
"""
from app.graph.parts.d_part.schemas import DPartGraphState, get_active_query
from app.llm import d_part as llm_d_part


async def route_recognition(state: DPartGraphState) -> DPartGraphState:
    result = await llm_d_part.call_recognition_check(get_active_query(state))
    state["recognized"] = bool(result.get("recognized"))
    return state
