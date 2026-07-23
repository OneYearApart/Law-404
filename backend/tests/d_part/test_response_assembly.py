"""
response_assembly 노드 테스트 (DB/네트워크는 monkeypatch로 흉내).
"""

import pytest

from app.graph.parts.d_part.nodes import response_assembly
from app.graph.parts.d_part.schemas import (
    SlotStatus,
    VictimJudgment,
    VictimRequirementSlots,
)
from app.rag.retrievers.base import Chunk


def _make_chunk(source_type: str, content: str) -> Chunk:
    return Chunk(id=1, source_type=source_type, content=content)


@pytest.mark.asyncio
async def test_assembles_response_when_judgment_just_computed(monkeypatch):
    seen = {}

    async def _fake_search_by_requirement(slots, situation_query=None):
        seen["situation_query"] = situation_query
        return {
            "statute": [_make_chunk("법령원문", "제3조 요건")],
            "case_law": [_make_chunk("판례", "판례 내용")],
            "cases": [],
            "guides": [
                _make_chunk("생활법령", "상황적용 안내")
            ],  # 작업단위 51 상황적용 grounding
        }

    async def _fake_generate_response(context: str, answer_kind: str):
        yield "원문 "
        yield "해설 "
        yield "상황적용"

    monkeypatch.setattr(
        response_assembly._retriever,
        "search_by_requirement",
        _fake_search_by_requirement,
    )
    monkeypatch.setattr(
        response_assembly.llm_d_part, "generate_response", _fake_generate_response
    )

    slots = VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus.FILLED,
        deposit_under_limit=SlotStatus.FILLED,
        multiple_victims=SlotStatus.FILLED,
        no_intent_to_return=SlotStatus.FILLED,
    )
    state = {
        "victim_slots": slots,
        "victim_judgment": VictimJudgment.HIGH,
        "needs_response_assembly": True,
        "final_answer": None,
        "user_input": "임차권등기명령은 어떻게 신청하나요",
    }

    result = await response_assembly.assemble_response(state)

    assert result["response_stream"] is not None
    chunks = [c async for c in result["response_stream"]]
    assert chunks == ["원문 ", "해설 ", "상황적용"]
    # final_answer는 일부러 None으로 남겨둠 — 전체 텍스트 조립은 스트림을 소비하는
    # 호출부(routes/d_part.py) 책임 (ainvoke() 반환값은 사후 state 변경을 못 봄)
    assert result["final_answer"] is None
    # 상황적용 grounding(생활법령)이 retrieved_chunks에 합쳐짐 → 근거 카드(46)에도 노출
    assert len(result["retrieved_chunks"]) == 3
    assert any(c.source_type == "생활법령" for c in result["retrieved_chunks"])
    assert (
        seen["situation_query"] == "임차권등기명령은 어떻게 신청하나요"
    )  # 사용자 발화 전달


@pytest.mark.asyncio
async def test_noop_when_no_judgment():
    state = {"victim_judgment": None}

    result = await response_assembly.assemble_response(state)

    assert result.get("response_stream") is None


@pytest.mark.asyncio
async def test_noop_when_already_has_final_answer():
    state = {
        "victim_judgment": VictimJudgment.HIGH,
        "final_answer": "이미 있음",
        "victim_slots": VictimRequirementSlots(),
    }

    result = await response_assembly.assemble_response(state)

    assert result.get("response_stream") is None


@pytest.mark.asyncio
async def test_no_rag_or_llm_call_on_turns_after_judgment(monkeypatch):
    """판정이 이미 확정된 과거 턴(victim_judgment는 세션에 남아 있지만 이번 턴에 새로
    확정된 게 아님)에는 RAG/LLM을 한 번도 재호출하면 안 된다 — 종결 후 매 턴 같은 판정
    응답을 재생성하던 비용/지연 버그의 회귀 테스트."""
    calls = {"retrieve": 0, "generate": 0}

    async def _counting_search_by_requirement(slots, situation_query=None):
        calls["retrieve"] += 1
        return {"statute": [], "case_law": [], "cases": [], "guides": []}

    async def _counting_generate_response(context: str, answer_kind: str):
        calls["generate"] += 1
        yield "재생성된 응답"

    monkeypatch.setattr(
        response_assembly._retriever,
        "search_by_requirement",
        _counting_search_by_requirement,
    )
    monkeypatch.setattr(
        response_assembly.llm_d_part, "generate_response", _counting_generate_response
    )

    state = {
        "victim_judgment": VictimJudgment.HIGH,
        "victim_slots": VictimRequirementSlots(),
        "final_answer": None,
    }

    result = await response_assembly.assemble_response(state)

    assert calls == {"retrieve": 0, "generate": 0}
    assert result.get("response_stream") is None


# --- 컨텍스트가 내부 필드명을 노출하지 않아야 한다 -------------------------------


def test_context_uses_korean_labels_not_internal_field_names():
    """슬롯을 model_dump로 통째로 넘기면 모델이 영문 키를 답변에 그대로 옮겨 적는다
    (실제로 "'moved_in_and_fixed_date' 요건이 충족된 반면…"이 사용자에게 노출됐다)."""
    from app.graph.parts.d_part.nodes.response_assembly import _format_context

    state = {
        "victim_slots": VictimRequirementSlots(
            moved_in_and_fixed_date=SlotStatus.FILLED,
            deposit_under_limit=SlotStatus.FILLED,
            multiple_victims=SlotStatus.FILLED,
            no_intent_to_return=SlotStatus.UNFILLED,
            has_relief_measure=False,
            auction_completed=True,
        ),
        "victim_judgment": VictimJudgment.NEEDS_CONFIRMATION,
        "retrieved_chunks": [],
    }

    context = _format_context(state)

    for field_name in (
        "moved_in_and_fixed_date",
        "deposit_under_limit",
        "multiple_victims",
        "no_intent_to_return",
    ):
        assert field_name not in context
    assert "전입신고·확정일자" in context and "충족" in context
    assert "미충족" in context  # no_intent_to_return이 UNFILLED
    assert VictimJudgment.NEEDS_CONFIRMATION.value in context


def test_context_hides_control_flags_that_are_not_requirements():
    """auction_completed(면제 플래그)·has_relief_measure(제외 사유)는 요건이 아니다.
    함께 던지면 모델이 "has_relief_measure 요건이 충족되지 않았습니다"처럼 쓰는데,
    구제수단이 없다는 건 오히려 지원 대상이라는 뜻이라 정반대로 읽힌다."""
    from app.graph.parts.d_part.nodes.response_assembly import _format_context

    state = {
        "victim_slots": VictimRequirementSlots(
            has_relief_measure=False, auction_completed=True
        ),
        "victim_judgment": VictimJudgment.HIGH,
        "retrieved_chunks": [],
    }

    context = _format_context(state)

    assert "has_relief_measure" not in context
    assert "auction_completed" not in context
