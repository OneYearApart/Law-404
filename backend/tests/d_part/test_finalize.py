"""
finalize 노드 테스트 (DB/네트워크 접근 없는 순수 로직).

단위 30: 면책 문구를 법률 정보 응답에만 정확히 1회 첨부, 확인질문/fallthrough엔 생략.
판단언어 금칙어는 차단하지 않고 경고 로그만 남긴다.
"""
import logging

import pytest

from app.graph.parts.d_part.nodes._disclaimer import DISCLAIMER
from app.graph.parts.d_part.nodes.finalize import finalize_response


async def _collect(state) -> str:
    return "".join([c async for c in state["response_stream"]])


@pytest.mark.asyncio
async def test_confirmation_question_has_no_disclaimer():
    """단순 확인질문(disclaimer_required 없음)에는 면책을 붙이지 않는다."""
    state = {"final_answer": "확인 질문입니다"}

    result = await finalize_response(state)

    assert await _collect(result) == "확인 질문입니다"
    assert DISCLAIMER not in result["final_answer"]


@pytest.mark.asyncio
async def test_fallthrough_message_when_no_final_answer():
    state = {}

    result = await finalize_response(state)

    text = await _collect(result)
    assert text == result["final_answer"]
    assert DISCLAIMER not in text


@pytest.mark.asyncio
async def test_legal_fixed_answer_gets_disclaimer_once():
    """special_cases/victim_check 제외판정 등 법률 정보 고정응답엔 면책이 정확히 1회."""
    state = {"final_answer": "임대인이 사망한 경우 상속인에게 청구할 수 있습니다.", "disclaimer_required": True}

    result = await finalize_response(state)
    text = await _collect(result)

    assert text.count(DISCLAIMER) == 1
    assert text.endswith(DISCLAIMER)
    # messages 저장용 final_answer도 스트림과 동일하게 면책을 포함해야 이력이 일치한다
    assert result["final_answer"].count(DISCLAIMER) == 1


@pytest.mark.asyncio
async def test_llm_stream_exposes_disclaimer_as_slot_not_inline():
    """LLM 응답 스트림은 항상 법률 정보 → 면책이 반드시 따라붙는다. 단 스트림에 인라인하지 않고
    disclaimer_text 슬롯으로 넘긴다(호출부가 구조화해 내보내고 저장 텍스트에 이어붙임)."""
    async def _llm_stream():
        yield "해설 "
        yield "상황적용"

    state = {"response_stream": _llm_stream()}

    result = await finalize_response(state)
    text = await _collect(result)

    assert text == "해설 상황적용"       # 본문만 — 평문에 면책이 섞이지 않는다
    assert result["disclaimer_text"] == DISCLAIMER


@pytest.mark.asyncio
async def test_banned_judgment_language_logs_warning(caplog):
    """금칙어(단정 표현)가 섞이면 응답은 그대로 나가되 경고 로그가 남는다."""
    async def _llm_stream():
        yield "이 경우 전세사기피해자에 해당됩니다."  # "됩니다" 금칙

    state = {"response_stream": _llm_stream()}

    result = await finalize_response(state)
    with caplog.at_level(logging.WARNING, logger="app.graph.parts.d_part.nodes.finalize"):
        text = await _collect(result)

    assert "해당됩니다" in text  # 차단하지 않음
    assert any("금칙어" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_clean_response_logs_no_warning(caplog):
    async def _llm_stream():
        yield "위험도는 추가확인이 필요합니다."

    state = {"response_stream": _llm_stream()}

    result = await finalize_response(state)
    with caplog.at_level(logging.WARNING, logger="app.graph.parts.d_part.nodes.finalize"):
        await _collect(result)

    assert not [rec for rec in caplog.records if "금칙어" in rec.message]


# --- 단위 44: 지원절차 액션플랜 첨부(스트림 경로) -----------------------------------

@pytest.mark.asyncio
async def test_action_plan_stays_out_of_body_stream():
    """판정 확정 턴: 액션플랜은 본문 평문에 섞이지 않고 슬롯에 남아 있어야 한다 —
    프론트가 정규식으로 '■'를 찾아 쪼개는 걸 막는 게 이 구조의 목적이다."""
    async def _body():
        yield "해설 상황적용"

    state = {
        "response_stream": _body(),
        "appendix_text": "■ 지금 확인·실행하실 점\n- ...",
    }

    result = await finalize_response(state)
    out = await _collect(result)

    assert "■" not in out
    assert out == "해설 상황적용"
    assert result["appendix_text"] == "■ 지금 확인·실행하실 점\n- ..."
    assert result["disclaimer_text"] == DISCLAIMER


@pytest.mark.asyncio
async def test_no_appendix_text_yields_body_only():
    """appendix_text가 없는 턴(일반 질의응답)은 본문만 — 면책은 여전히 슬롯으로 보장된다."""
    async def _body():
        yield "본문"

    state = {"response_stream": _body()}          # appendix_text 없음

    result = await finalize_response(state)
    out = await _collect(result)

    assert out == "본문"
    assert result.get("appendix_text") is None
    assert result["disclaimer_text"] == DISCLAIMER


@pytest.mark.asyncio
async def test_fixed_text_path_unaffected_by_action_plan():
    """고정 텍스트 경로(special_cases 등)는 appendix_text가 실수로 있어도 붙이지 않는다."""
    state = {
        "final_answer": "특수상황 안내문",
        "disclaimer_required": True,
        "appendix_text": "붙으면 안 되는 텍스트",
    }

    out = await _collect(await finalize_response(state))

    assert "특수상황 안내문" in out
    assert "붙으면 안 되는 텍스트" not in out       # 스트림 경로에서만 첨부
    assert DISCLAIMER in out
