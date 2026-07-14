"""
graph.py 라우팅 함수 단위테스트 + 전체 그래프 종단 스모크 테스트.
LLM/RAG 호출은 전부 monkeypatch로 흉내내고 DB 접근 없음.
"""
import pytest

from app.graph.parts.d_part import graph as graph_module
from app.graph.parts.d_part.nodes import (
    general_scenario,
    open_qa,
    response_assembly,
    stage_router,
    supervisor,
    victim_check,
)
from app.graph.parts.d_part.schemas import SlotStatus, Stage, VictimJudgment, VictimRequirementSlots
from app.rag.retrievers.base import Chunk


def _fake_confirmation(answer):
    async def _fake(question: str, user_input: str):
        return answer

    return _fake


def test_route_after_supervisor_pending_final_answer_goes_to_finalize():
    state = {"final_answer": "확인 질문", "route_target": "open_qa"}
    assert graph_module._route_after_supervisor(state) == "finalize"


@pytest.mark.parametrize(
    "route_target",
    ["victim_check", "special_cases", "general_scenario", "open_qa"],
)
def test_route_after_supervisor_follows_route_target(route_target):
    state = {"route_target": route_target}
    assert graph_module._route_after_supervisor(state) == route_target


@pytest.mark.asyncio
async def test_full_graph_continues_pending_relief_question_to_judgment_response(monkeypatch):
    """진행 중이던 victim_check(구제수단 질문 대기)를 이어받아 판단 확정 + 응답 조립까지 가는 종단 경로.
    supervisor는 진행 중 흐름을 감지해 LLM 호출 없이 바로 victim_check로 보내야 한다."""

    async def _unreachable_call_supervisor(user_input: str) -> dict:
        raise AssertionError("진행 중인 흐름이 있을 땐 supervisor가 LLM을 호출하면 안 된다")

    async def _fake_search_by_requirement(slots):
        return {"statute": [Chunk(id=1, source_type="법령원문", content="제3조")], "case_law": [], "cases": []}

    async def _fake_generate_response(context: str):
        yield "판단 응답"

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _unreachable_call_supervisor)
    monkeypatch.setattr(victim_check, "parse_confirmation", _fake_confirmation(False))
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

    async def _fake_call_supervisor(user_input: str) -> dict:
        return {"category": "general_topic:전-①등기부등본_위험신호"}

    async def _fake_search_by_topic(topic_key, query_text):
        return {"statute": [Chunk(id=1, source_type="법령원문", content="관련 조문")], "case_law": [], "cases": []}

    async def _fake_generate_response(context: str):
        yield "일반 시나리오 응답"

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake_call_supervisor)
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
async def test_full_graph_matches_topic_from_a_different_stage_than_confirmed(monkeypatch):
    """확정된 계약단계(중)와 다른 단계 접두어를 가진 항목(전-③)도 매칭돼야 한다 — supervisor
    도입 전엔 general_scenario가 확정 단계의 항목만 후보로 놓아서 이런 질문이 무조건
    fallthrough로 빠졌다(2026-07-14에 고친 지점)."""

    async def _fake_call_supervisor(user_input: str) -> dict:
        return {"category": "general_topic:전-③다가구_선순위보증금"}

    async def _fake_search_by_topic(topic_key, query_text):
        return {"statute": [Chunk(id=1, source_type="법령원문", content="관련 조문")], "case_law": [], "cases": []}

    async def _fake_generate_response(context: str):
        yield "다가구주택 답변"

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake_call_supervisor)
    monkeypatch.setattr(general_scenario._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(general_scenario.llm_d_part, "generate_response", _fake_generate_response)

    initial_state = {
        "user_input": "다가구주택인데 선순위 보증금이 걱정돼요",
        "stage": Stage.DURING,
        "stage_confirmed": True,
    }

    result = await graph_module.graph.ainvoke(initial_state)

    assert result["general_topic_matched"] == "전-③다가구_선순위보증금"
    chunks = [c async for c in result["response_stream"]]
    assert "".join(chunks) == "다가구주택 답변"


@pytest.mark.asyncio
async def test_full_graph_routes_unmatched_question_to_open_qa_instead_of_fallthrough(monkeypatch):
    """13개 항목/특수상황/위험신호 어디에도 안 걸리는 질문은 open_qa에서 실제 RAG 응답을
    받아야 하며, finalize의 fallthrough 문구로 빠지면 안 된다."""

    async def _fake_call_supervisor(user_input: str) -> dict:
        return {"category": "open_qa"}

    async def _fake_search(query: str, top_k: int = 5):
        return [Chunk(id=1, source_type="판례", content="관련 판례")]

    async def _fake_generate_response(context: str):
        yield "open_qa 응답"

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake_call_supervisor)
    monkeypatch.setattr(open_qa._retriever, "search", _fake_search)
    monkeypatch.setattr(open_qa.llm_d_part, "generate_response", _fake_generate_response)

    initial_state = {
        "user_input": "보증금 반환청구 소송은 어떻게 진행하나요",
        "stage": Stage.DURING,
        "stage_confirmed": True,
    }

    result = await graph_module.graph.ainvoke(initial_state)

    chunks = [c async for c in result["response_stream"]]
    joined = "".join(chunks)
    assert joined == "open_qa 응답"
    assert "안내드릴 내용이 없습니다" not in joined


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "closed_session",
    [
        pytest.param(
            {
                "victim_judgment": VictimJudgment.HIGH,
                "victim_flow_closed": True,
                "victim_slots": VictimRequirementSlots(
                    moved_in_and_fixed_date=SlotStatus.FILLED,
                    deposit_under_limit=SlotStatus.FILLED,
                    multiple_victims=SlotStatus.FILLED,
                    no_intent_to_return=SlotStatus.FILLED,
                    has_relief_measure=False,
                ),
            },
            id="판정확정",
        ),
        pytest.param(
            {
                "victim_flow_closed": True,
                "victim_slots": VictimRequirementSlots(
                    moved_in_and_fixed_date=SlotStatus.FILLED,
                    deposit_under_limit=SlotStatus.FILLED,
                    multiple_victims=SlotStatus.FILLED,
                    no_intent_to_return=SlotStatus.FILLED,
                    has_relief_measure=True,
                ),
            },
            id="지원대상제외",
        ),
        pytest.param(
            {
                "victim_fallback": True,
                "victim_flow_closed": True,
                "victim_check_attempts": 3,
                "victim_slots": VictimRequirementSlots(moved_in_and_fixed_date=SlotStatus.UNCLEAR),
            },
            id="fallback",
        ),
    ],
)
async def test_full_graph_reclassifies_followup_after_victim_flow_closed(monkeypatch, closed_session):
    """victim_check 인터뷰가 종결된 대화방에서 무관한 후속 질문이 오면 정상 재분류돼야 한다.
    종결 상태(판정/제외/fallback)가 세션에 영속되는 탓에 모든 후속 턴이 victim_check로 영구히
    고정되던 버그의 회귀 테스트 — 판정 확정 경로에선 응답까지 매 턴 재생성되고 있었다."""

    async def _fake_call_supervisor(user_input: str) -> dict:
        return {"category": "open_qa"}

    async def _fake_search(query: str, top_k: int = 5):
        return [Chunk(id=1, source_type="법령원문", content="보증보험 관련 조문")]

    async def _fake_generate_response(context: str):
        yield "보증보험 안내"

    async def _unreachable_search_by_requirement(slots):
        raise AssertionError("종결된 인터뷰의 후속 턴에서 판정 응답을 재조립하면 안 된다")

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake_call_supervisor)
    monkeypatch.setattr(open_qa._retriever, "search", _fake_search)
    monkeypatch.setattr(open_qa.llm_d_part, "generate_response", _fake_generate_response)
    monkeypatch.setattr(response_assembly._retriever, "search_by_requirement", _unreachable_search_by_requirement)

    initial_state = {
        "user_input": "전세보증보험은 언제 가입하나요?",
        "stage": Stage.DURING,
        "stage_confirmed": True,
        **closed_session,
    }

    result = await graph_module.graph.ainvoke(initial_state)

    assert result["route_target"] == "open_qa"
    # 종결 플래그는 victim_check를 거치지 않는 턴에도 그대로 살아남아 다음 턴에 재저장돼야 한다
    assert result["victim_flow_closed"] is True
    joined = "".join([c async for c in result["response_stream"]])
    assert joined == "보증보험 안내"
    assert "안내드릴 내용이 없습니다" not in joined


@pytest.mark.asyncio
async def test_stage_confirmation_reply_does_not_lose_original_question(monkeypatch):
    """턴1: 실질 질문 → 단계 확인질문. 턴2: '네' → 원래 질문에 대한 답이 나와야 하며
    '안내드릴 내용이 없습니다' 폴백으로 떨어지면 안 된다 (재현된 버그의 회귀 테스트)."""

    async def _fake_call_stage_router(user_input: str) -> dict:
        return {"stage": "전"}

    async def _fake_call_supervisor(user_input: str) -> dict:
        return {"category": "general_topic:전-①등기부등본_위험신호"}

    async def _fake_search_by_topic(topic_key, query_text):
        return {"statute": [Chunk(id=1, source_type="법령원문", content="등기부 관련 조문")], "case_law": [], "cases": []}

    async def _fake_generate_response(context: str):
        yield "등기부등본 답변"

    monkeypatch.setattr(stage_router.llm_d_part, "call_stage_router", _fake_call_stage_router)
    monkeypatch.setattr(stage_router, "parse_confirmation", _fake_confirmation(True))
    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake_call_supervisor)
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
