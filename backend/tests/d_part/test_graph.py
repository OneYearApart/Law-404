"""
graph.py 라우팅 함수 단위테스트 + 전체 그래프 종단 스모크 테스트.
LLM/RAG 호출은 전부 monkeypatch로 흉내내고 DB 접근 없음.
"""
import pytest

from app.graph.parts.d_part import graph as graph_module
from app.graph.parts.d_part.nodes._disclaimer import DISCLAIMER
from app.graph.parts.d_part.nodes import (
    _open_search,
    general_scenario,
    open_qa,
    recognized_general,
    response_assembly,
    special_cases,
    support_data,
    supervisor,
    victim_check,
)
from app.graph.parts.d_part.schemas import (
    SituationState,
    SlotStatus,
    VictimJudgment,
    VictimRequirementSlots,
)
from app.rag.retrievers.base import Chunk


def _fake_confirmation(answer):
    async def _fake(question: str, user_input: str):
        return answer

    return _fake


@pytest.mark.parametrize(
    "situation, expected",
    [
        (SituationState(recognized=True, special_case="신탁사기"), "special_cases"),
        (SituationState(recognized=True), "recognized_general"),
        (SituationState(recognized=False, risk_signals=["보증금미반환"]), "victim_check"),
        (SituationState(recognized=False, topic="전-①등기부등본_위험신호"), "general_scenario"),
        (SituationState(recognized=False), "open_qa"),
    ],
)
def test_route_after_supervisor_derives_from_situation(situation, expected):
    """엣지가 상황모델에서 직접 파생시킨다 — supervisor가 써둔 라우팅 대상을 읽지 않는다."""
    assert graph_module._route_after_supervisor({"situation": situation}) == expected


def test_route_after_supervisor_continues_interview_without_reclassifying():
    """인터뷰 진행 중이면 남아 있는 직전 턴 situation을 보지 않고 victim_check로 이어간다."""
    state = {
        "situation": SituationState(recognized=False, topic="전-①등기부등본_위험신호"),
        "victim_slots": VictimRequirementSlots(moved_in_and_fixed_date=SlotStatus.FILLED),
    }
    assert graph_module._route_after_supervisor(state) == "victim_check"


@pytest.mark.asyncio
async def test_full_graph_continues_pending_relief_question_to_judgment_response(monkeypatch):
    """진행 중이던 victim_check(구제수단 질문 대기)를 이어받아 판단 확정 + 응답 조립까지 가는 종단 경로.
    supervisor는 진행 중 흐름을 감지해 LLM 호출 없이 바로 victim_check로 보내야 한다."""

    async def _unreachable_call_supervisor(user_input: str) -> dict:
        raise AssertionError("진행 중인 흐름이 있을 땐 supervisor가 LLM을 호출하면 안 된다")

    async def _fake_search_by_requirement(slots, situation_query=None):
        return {"statute": [Chunk(id=1, source_type="법령원문", content="제3조")], "case_law": [], "cases": [], "guides": []}

    async def _fake_generate_response(context: str, answer_kind: str):
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
        "victim_slots": slots,
        "awaiting_relief_confirmation": True,
    }

    result = await graph_module.graph.ainvoke(initial_state)

    assert result["victim_judgment"] == VictimJudgment.HIGH
    assert result["response_stream"] is not None
    joined = "".join([c async for c in result["response_stream"]])
    assert joined.startswith("판단 응답")
    # 법률 정보 응답 → 면책 보장. 스트림엔 인라인하지 않고 슬롯으로 넘긴다(호출부가 구조화해 첨부)
    assert result["disclaimer_text"] == DISCLAIMER


@pytest.mark.asyncio
async def test_full_graph_no_risk_signal_routes_to_general_scenario(monkeypatch):
    """위험신호도 없고 진행 중인 흐름도 없는 턴은 general_scenario에서 항목 매칭+응답 조립까지 간다."""

    async def _fake_call_supervisor(user_input: str) -> dict:
        return {"recognized": False, "risk_signals": [], "topic": "전-①등기부등본_위험신호"}

    async def _fake_search_by_topic(topic_key, query_text):
        return {"statute": [Chunk(id=1, source_type="법령원문", content="관련 조문")], "case_law": [], "cases": [], "guides": []}

    async def _fake_generate_response(context: str, answer_kind: str):
        yield "일반 시나리오 응답"

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake_call_supervisor)
    monkeypatch.setattr(general_scenario._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(general_scenario.llm_d_part, "generate_response", _fake_generate_response)

    initial_state = {
        "user_input": "등기부등본에 근저당이 많이 잡혀있어서 불안해요",
    }

    result = await graph_module.graph.ainvoke(initial_state)

    assert result["situation"].topic == "전-①등기부등본_위험신호"
    assert result["response_stream"] is not None
    joined = "".join([c async for c in result["response_stream"]])
    assert joined.startswith("일반 시나리오 응답")
    assert result["disclaimer_text"] == DISCLAIMER


@pytest.mark.asyncio
async def test_full_graph_matches_topic_from_a_different_stage_than_confirmed(monkeypatch):
    """확정된 계약단계(중)와 다른 단계 접두어를 가진 항목(전-③)도 매칭돼야 한다 — supervisor
    도입 전엔 general_scenario가 확정 단계의 항목만 후보로 놓아서 이런 질문이 무조건
    fallthrough로 빠졌다(2026-07-14에 고친 지점)."""

    async def _fake_call_supervisor(user_input: str) -> dict:
        return {"recognized": False, "risk_signals": [], "topic": "전-③다가구_선순위보증금"}

    async def _fake_search_by_topic(topic_key, query_text):
        return {"statute": [Chunk(id=1, source_type="법령원문", content="관련 조문")], "case_law": [], "cases": [], "guides": []}

    async def _fake_generate_response(context: str, answer_kind: str):
        yield "다가구주택 답변"

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake_call_supervisor)
    monkeypatch.setattr(general_scenario._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(general_scenario.llm_d_part, "generate_response", _fake_generate_response)

    initial_state = {
        "user_input": "다가구주택인데 선순위 보증금이 걱정돼요",
    }

    result = await graph_module.graph.ainvoke(initial_state)

    assert result["situation"].topic == "전-③다가구_선순위보증금"
    joined = "".join([c async for c in result["response_stream"]])
    assert joined.startswith("다가구주택 답변")
    assert result["disclaimer_text"] == DISCLAIMER


@pytest.mark.asyncio
async def test_full_graph_routes_unmatched_question_to_open_qa_instead_of_fallthrough(monkeypatch):
    """13개 항목/특수상황/위험신호 어디에도 안 걸리는 질문은 open_qa에서 실제 RAG 응답을
    받아야 하며, finalize의 fallthrough 문구로 빠지면 안 된다."""

    async def _fake_call_supervisor(user_input: str) -> dict:
        return {"recognized": False, "risk_signals": []}

    async def _fake_search_balanced(query, quota=None):
        return [Chunk(id=1, source_type="법령원문", content="관련 조문")]

    async def _fake_generate_response(context: str, answer_kind: str):
        yield "open_qa 응답"

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake_call_supervisor)
    monkeypatch.setattr(_open_search.retriever, "search_balanced", _fake_search_balanced)
    monkeypatch.setattr(open_qa.llm_d_part, "generate_response", _fake_generate_response)

    initial_state = {
        "user_input": "보증금 반환청구 소송은 어떻게 진행하나요",
    }

    result = await graph_module.graph.ainvoke(initial_state)

    joined = "".join([c async for c in result["response_stream"]])
    assert joined.startswith("open_qa 응답")
    assert result["disclaimer_text"] == DISCLAIMER
    assert "안내드릴 내용이 없습니다" not in joined


@pytest.mark.asyncio
async def test_full_graph_routes_recognized_victim_to_recognized_general(monkeypatch):
    """인정받았지만 특수 4종에도 13개 항목에도 안 걸리는 피해자는 open_qa가 아니라 전용 경로로
    가서, 사용자 상황을 모른다고 전제한 일반론 대신 인지형 응답 + 지원절차 개요를 받아야 한다."""

    async def _fake_call_supervisor(user_input: str) -> dict:
        return {"recognized": True, "risk_signals": ["보증금미반환"]}

    async def _fake_search_balanced(query, quota=None):
        return [Chunk(id=1, source_type="법령원문", content="전세사기피해자법 제3조")]

    async def _fake_generate_response(context: str, answer_kind: str):
        yield "인지형 응답"

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake_call_supervisor)
    monkeypatch.setattr(_open_search.retriever, "search_balanced", _fake_search_balanced)
    monkeypatch.setattr(recognized_general.llm_d_part, "generate_response", _fake_generate_response)

    result = await graph_module.graph.ainvoke(
        {"user_input": "피해자로 인정받았는데 보증금을 아직 못 받고 있어요"}
    )

    # answer_kind는 응답을 만든 노드가 세팅하므로 어느 노드가 실행됐는지의 증거가 된다
    # (open_qa로 샜다면 "open_qa"가 들어온다). llm_d_part는 두 노드가 공유하는 같은 모듈
    # 객체라 "open_qa엔 절대 안 간다"를 monkeypatch 가드로 세울 수는 없다 — 뒤 patch가 앞을 덮는다.
    assert result["answer_kind"] == "recognized_general"
    # 지원절차 개요는 support_appendix가 상황(recognized)을 보고 붙인다 — 이 경로가
    # 직접 세팅하지 않아도 종단에서는 붙어 있어야 한다(D3 부착 일관성)
    assert result["appendix_text"] == support_data._RECOGNIZED_GUIDANCE
    joined = "".join([c async for c in result["response_stream"]])
    assert joined.startswith("인지형 응답")
    assert result["disclaimer_text"] == DISCLAIMER


@pytest.mark.asyncio
async def test_full_graph_special_case_still_gets_its_guidance(monkeypatch):
    """부착점을 옮긴 뒤에도 특수상황 안내가 그대로 붙는지 — special_cases는 자기 노드에서
    inline으로 붙이던 것을 잃었고, 이제 support_appendix가 상황을 보고 같은 텍스트를 붙인다.
    (이 경로는 예전에 유닛 그린인 채로 통째로 죽어 있던 전적이 있어 종단으로 못 박는다.)"""

    async def _fake_call_supervisor(user_input: str) -> dict:
        return {"recognized": True, "risk_signals": [], "special_case": "신탁사기"}

    async def _fake_search_by_topic(topic_key, query_text):
        return {"statute": [Chunk(id=1, source_type="법령원문", content="관련 조문")],
                "case_law": [], "cases": [], "guides": []}

    async def _fake_generate_response(context: str, answer_kind: str):
        yield "신탁사기 해설"

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake_call_supervisor)
    monkeypatch.setattr(special_cases._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(special_cases.llm_d_part, "generate_response", _fake_generate_response)

    result = await graph_module.graph.ainvoke(
        {"user_input": "신탁 등기가 되어 있고 이미 피해자로 인정받았어요"}
    )

    assert result["answer_kind"] == "special_case"
    assert result["appendix_text"] == support_data._SPECIAL_CASE_GUIDANCE["신탁사기"]
    assert result["disclaimer_text"] == DISCLAIMER


@pytest.mark.asyncio
async def test_full_graph_attaches_support_guidance_on_general_scenario_when_recognized(monkeypatch):
    """인정받은 사용자가 13개 항목을 물으면 general_scenario가 답하지만 지원절차 안내는 붙는다.

    부착이 실행 경로에 묶여 있던 시절엔 topic이 잡혔다는 이유만으로 안내가 사라졌다 —
    같은 사용자가 같은 상황인데 무엇을 물었느냐로 부가기능이 나타났다 사라진 것이다(D3)."""

    async def _fake_call_supervisor(user_input: str) -> dict:
        # 전-③/⑤/⑥이 아닌 topic이라 special_case로 파생되지 않는다 → general_scenario로 간다
        return {"recognized": True, "risk_signals": [], "topic": "후-②이중계약_배당순위"}

    async def _fake_search_by_topic(topic_key, query_text):
        return {"statute": [Chunk(id=1, source_type="법령원문", content="관련 조문")],
                "case_law": [], "cases": [], "guides": []}

    async def _fake_generate_response(context: str, answer_kind: str):
        yield "배당순위 답변"

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake_call_supervisor)
    monkeypatch.setattr(general_scenario._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(general_scenario.llm_d_part, "generate_response", _fake_generate_response)

    result = await graph_module.graph.ainvoke(
        {"user_input": "피해자로 인정받았는데 배당순위 다툼이 있어요"}
    )

    assert result["answer_kind"] == "scenario"
    assert result["appendix_text"] == support_data._RECOGNIZED_GUIDANCE


@pytest.mark.asyncio
async def test_full_graph_attaches_nothing_on_general_scenario_when_not_recognized(monkeypatch):
    """같은 경로라도 인정 전 사용자에겐 지원절차 안내가 붙지 않는다 — 부착을 정하는 건
    경로가 아니라 상황이라는 것의 반대편 증거."""

    async def _fake_call_supervisor(user_input: str) -> dict:
        return {"recognized": False, "risk_signals": [], "topic": "후-②이중계약_배당순위"}

    async def _fake_search_by_topic(topic_key, query_text):
        return {"statute": [Chunk(id=1, source_type="법령원문", content="관련 조문")],
                "case_law": [], "cases": [], "guides": []}

    async def _fake_generate_response(context: str, answer_kind: str):
        yield "배당순위 답변"

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake_call_supervisor)
    monkeypatch.setattr(general_scenario._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(general_scenario.llm_d_part, "generate_response", _fake_generate_response)

    result = await graph_module.graph.ainvoke({"user_input": "배당순위 다툼이 걱정돼요"})

    assert result["answer_kind"] == "scenario"
    assert result.get("appendix_text") is None


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
        return {"recognized": False, "risk_signals": []}

    async def _fake_search_balanced(query, quota=None):
        return [Chunk(id=1, source_type="법령원문", content="보증보험 관련 조문")]

    async def _fake_generate_response(context: str, answer_kind: str):
        yield "보증보험 안내"

    async def _unreachable_search_by_requirement(slots):
        raise AssertionError("종결된 인터뷰의 후속 턴에서 판정 응답을 재조립하면 안 된다")

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake_call_supervisor)
    monkeypatch.setattr(_open_search.retriever, "search_balanced", _fake_search_balanced)
    monkeypatch.setattr(open_qa.llm_d_part, "generate_response", _fake_generate_response)
    monkeypatch.setattr(response_assembly._retriever, "search_by_requirement", _unreachable_search_by_requirement)

    initial_state = {
        "user_input": "전세보증보험은 언제 가입하나요?",
        **closed_session,
    }

    result = await graph_module.graph.ainvoke(initial_state)

    # 종결 플래그는 victim_check를 거치지 않는 턴에도 그대로 살아남아 다음 턴에 재저장돼야 한다
    assert result["victim_flow_closed"] is True
    joined = "".join([c async for c in result["response_stream"]])
    assert joined.startswith("보증보험 안내")
    assert result["disclaimer_text"] == DISCLAIMER
    assert "안내드릴 내용이 없습니다" not in joined


@pytest.mark.asyncio
async def test_first_turn_answers_directly_without_stage_gate(monkeypatch):
    """첫 턴의 실질 질문에 확인질문 왕복 없이 바로 답이 나와야 한다(단위 29).

    예전에는 stage_router가 첫 턴을 "'전' 단계로 보입니다. 맞으신가요?"에 통째로 쓰고
    사용자가 "네"라고 답한 다음 턴에야 원래 질문이 처리됐다. stage는 이제 supervisor의
    카테고리 키 접두어에서 역산하므로 그 왕복이 없다.
    """

    async def _fake_call_supervisor(user_input: str) -> dict:
        return {"recognized": False, "risk_signals": [], "topic": "전-①등기부등본_위험신호"}

    async def _fake_search_by_topic(topic_key, query_text):
        return {"statute": [Chunk(id=1, source_type="법령원문", content="등기부 관련 조문")], "case_law": [], "cases": [], "guides": []}

    async def _fake_generate_response(context: str, answer_kind: str):
        yield "등기부등본 답변"

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake_call_supervisor)
    monkeypatch.setattr(general_scenario._retriever, "search_by_topic", _fake_search_by_topic)
    monkeypatch.setattr(general_scenario.llm_d_part, "generate_response", _fake_generate_response)

    result = await graph_module.graph.ainvoke(
        {"user_input": "계약 전인데 등기부등본을 어떻게 봐야 하나요"}
    )

    assert result["situation"].topic == "전-①등기부등본_위험신호"
    assert result["response_stream"] is not None
    joined = "".join([c async for c in result["response_stream"]])
    assert joined.startswith("등기부등본 답변")
    assert result["disclaimer_text"] == DISCLAIMER
    assert "안내드릴 내용이 없습니다" not in joined
