"""
graph.py 라우팅 함수 단위테스트 + 전체 그래프 종단 스모크 테스트.
LLM/RAG 호출은 전부 monkeypatch로 흉내내고 DB 접근 없음.
"""
import pytest

from app.graph.parts.d_part import graph as graph_module
from app.graph.parts.d_part.nodes import general_scenario, response_assembly, risk_trigger, stage_router
from app.graph.parts.d_part.schemas import SlotStatus, Stage, VictimJudgment, VictimRequirementSlots
from app.rag.retrievers.base import Chunk


def test_route_after_risk_trigger_special_case_matched_wins():
    state = {"special_case_matched": "신탁사기", "risk_trigger_detected": False}
    assert graph_module._route_after_risk_trigger(state) == "special_cases"


@pytest.mark.parametrize(
    "state",
    [
        {"victim_judgment": VictimJudgment.HIGH},
        {"victim_fallback": True},
        {"awaiting_relief_confirmation": True},
        {"victim_slots": VictimRequirementSlots(moved_in_and_fixed_date=SlotStatus.FILLED)},
    ],
)
def test_route_after_risk_trigger_continues_in_progress_victim_check(state):
    # risk_trigger_detected가 이번 턴 False라도(재트리거 안 됨) 진행 중인 흐름은 계속돼야 함
    assert graph_module._route_after_risk_trigger(state) == "victim_check"


def test_route_after_risk_trigger_fresh_trigger_goes_to_recognition():
    state = {"risk_trigger_detected": True}
    assert graph_module._route_after_risk_trigger(state) == "recognition_router"


def test_route_after_risk_trigger_nothing_goes_to_general_scenario():
    state = {"risk_trigger_detected": False}
    assert graph_module._route_after_risk_trigger(state) == "general_scenario"


def test_route_after_recognition_recognized():
    assert graph_module._route_after_recognition({"recognized": True}) == "special_cases"


def test_route_after_recognition_not_recognized():
    assert graph_module._route_after_recognition({"recognized": False}) == "victim_check"


@pytest.mark.asyncio
async def test_full_graph_continues_pending_relief_question_to_judgment_response(monkeypatch):
    """진행 중이던 victim_check(구제수단 질문 대기)를 이어받아 판단 확정 + 응답 조립까지 가는 종단 경로."""

    async def _fake_call_risk_trigger(user_input: str) -> dict:
        return {"matched": False, "condition_no": None, "reason": None}

    async def _fake_search_by_requirement(slots):
        return {"statute": [Chunk(id=1, source_type="법령원문", content="제3조")], "case_law": [], "cases": []}

    async def _fake_generate_response(context: str):
        yield "판단 응답"

    monkeypatch.setattr(risk_trigger.llm_d_part, "call_risk_trigger", _fake_call_risk_trigger)
    monkeypatch.setattr(response_assembly._retriever, "search_by_requirement", _fake_search_by_requirement)
    monkeypatch.setattr(response_assembly.llm_d_part, "generate_response", _fake_generate_response)

    slots = VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus.FILLED,
        deposit_under_limit=SlotStatus.FILLED,
        multiple_victims=SlotStatus.FILLED,
        no_intent_to_return=SlotStatus.FILLED,
    )
    initial_state = {
        "user_input": "아니요 없어요",
        "stage": Stage.DURING,
        "stage_confirmed": True,
        "victim_slots": slots,
        "awaiting_relief_confirmation": True,
    }

    result = await graph_module.graph.ainvoke(initial_state)

    assert result["victim_judgment"] == VictimJudgment.HIGH
    assert result["response_stream"] is not None
    chunks = [c async for c in result["response_stream"]]
    assert chunks == ["판단 응답"]


@pytest.mark.asyncio
async def test_full_graph_no_risk_signal_routes_to_general_scenario(monkeypatch):
    """위험신호도 없고 진행 중인 흐름도 없는 턴은 general_scenario에서 항목 매칭+응답 조립까지 간다."""

    async def _fake_call_risk_trigger(user_input: str) -> dict:
        return {"matched": False, "condition_no": None, "reason": None}

    async def _fake_search_by_topic(topic_key, query_text):
        return {"statute": [Chunk(id=1, source_type="법령원문", content="관련 조문")], "case_law": [], "cases": []}

    async def _fake_generate_response(context: str):
        yield "일반 시나리오 응답"

    monkeypatch.setattr(risk_trigger.llm_d_part, "call_risk_trigger", _fake_call_risk_trigger)
    monkeypatch.setattr(general_scenario._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(general_scenario.llm_d_part, "generate_response", _fake_generate_response)

    initial_state = {
        "user_input": "등기부등본에 근저당이 많이 잡혀있어서 불안해요",
        "stage": Stage.PRE,
        "stage_confirmed": True,
    }

    result = await graph_module.graph.ainvoke(initial_state)

    assert result["general_topic_matched"] == "전-①등기부등본_위험신호"
    assert result["response_stream"] is not None
    chunks = [c async for c in result["response_stream"]]
    assert chunks == ["일반 시나리오 응답"]


@pytest.mark.asyncio
async def test_stage_confirmation_reply_does_not_lose_original_question(monkeypatch):
    """턴1: 실질 질문 → 단계 확인질문. 턴2: '네' → 원래 질문에 대한 답이 나와야 하며
    '안내드릴 내용이 없습니다' 폴백으로 떨어지면 안 된다 (재현된 버그의 회귀 테스트)."""

    async def _fake_call_stage_router(user_input: str) -> dict:
        return {"stage": "전"}

    async def _fake_call_risk_trigger(user_input: str) -> dict:
        return {"matched": False, "condition_no": None, "reason": None}

    async def _fake_search_by_topic(topic_key, query_text):
        return {"statute": [Chunk(id=1, source_type="법령원문", content="등기부 관련 조문")], "case_law": [], "cases": []}

    async def _fake_generate_response(context: str):
        yield "등기부등본 답변"

    monkeypatch.setattr(stage_router.llm_d_part, "call_stage_router", _fake_call_stage_router)
    monkeypatch.setattr(risk_trigger.llm_d_part, "call_risk_trigger", _fake_call_risk_trigger)
    monkeypatch.setattr(general_scenario._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(general_scenario.llm_d_part, "generate_response", _fake_generate_response)

    # 턴 1: 실질 질문 — 단계 판별 + 확인질문
    turn1_input = {"user_input": "계약 전인데 등기부등본을 어떻게 봐야 하나요"}
    turn1_result = await graph_module.graph.ainvoke(turn1_input)

    assert turn1_result["stage"] == Stage.PRE
    assert turn1_result["stage_confirmed"] is False
    assert turn1_result["active_query"] == turn1_input["user_input"]
    assert turn1_result["final_answer"] is not None

    # 턴 2: "네" — DPartSessionState로 영속화되는 필드만 실제 라우트 핸들러와 동일하게 다음 턴 입력에 반영
    turn2_input = {
        "user_input": "네",
        "stage": turn1_result["stage"],
        "stage_confirmed": turn1_result["stage_confirmed"],
        "active_query": turn1_result["active_query"],
    }
    turn2_result = await graph_module.graph.ainvoke(turn2_input)

    assert turn2_result["stage_confirmed"] is True
    assert turn2_result["general_topic_matched"] == "전-①등기부등본_위험신호"
    assert turn2_result["response_stream"] is not None
    chunks = [c async for c in turn2_result["response_stream"]]
    joined = "".join(chunks)
    assert joined == "등기부등본 답변"
    assert "안내드릴 내용이 없습니다" not in joined
