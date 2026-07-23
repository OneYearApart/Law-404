"""
경로별 응답 프롬프트 조합 테스트 (네트워크 없음 — 프롬프트 문자열만 검증).

네 경로(판정/시나리오/특수상황/자유질의)가 한 장을 공유하던 때는 "판단 결과가 없으면 …" 같은
조건이 프롬프트에 쌓여, 모델이 자기 경로에 없는 지시까지 읽어야 했다. 이제 각 경로는 자기
지시만 받는다. 인용·형식 규칙은 복제하면 드리프트가 나므로 response_common 한 곳에만 둔다.
"""

import pytest

from app.llm import d_part


class _StubStream:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def _capture_prompt(monkeypatch) -> list[str]:
    captured: list[str] = []

    async def _fake_create(**kwargs):
        captured.append(kwargs["messages"][0]["content"])
        return _StubStream()

    monkeypatch.setattr(d_part._client.chat.completions, "create", _fake_create)
    return captured


@pytest.mark.asyncio
@pytest.mark.parametrize("answer_kind", d_part.RESPONSE_ANSWER_KINDS)
async def test_every_kind_gets_common_rules_and_its_own_instructions(
    monkeypatch, answer_kind
):
    captured = _capture_prompt(monkeypatch)

    async for _ in d_part.generate_response("근거 컨텍스트", answer_kind):
        pass

    prompt = captured[0]
    assert (
        "### 해설" in prompt and "### 상황적용" in prompt
    )  # 공통 출력 형식(프론트 파싱 계약)
    assert "컨텍스트에 없는 조문·판례를 지어내지 마세요" in prompt  # 공통 인용 규칙
    assert "근거 컨텍스트" in prompt


@pytest.mark.asyncio
async def test_only_judgment_path_is_told_to_use_the_verdict_wording(monkeypatch):
    """판정이 없는 경로가 '높음/있음/추가확인'을 쓰라는 지시를 받으면 없는 판단을 지어낸다."""
    captured = _capture_prompt(monkeypatch)

    for kind in d_part.RESPONSE_ANSWER_KINDS:
        async for _ in d_part.generate_response("컨텍스트", kind):
            pass

    prompts = dict(zip(d_part.RESPONSE_ANSWER_KINDS, captured))
    assert "그대로 쓰세요" in prompts["judgment"]
    for kind in ("scenario", "special_case", "open_qa"):
        assert "위험도 판단(높음/있음/추가확인)을 붙이지 마세요" in prompts[kind]


@pytest.mark.asyncio
async def test_special_case_is_told_not_to_write_support_procedures(monkeypatch):
    """지원절차는 검수된 고정 텍스트를 시스템이 붙인다 — 모델이 또 쓰면 안내가 두 번 나간다."""
    captured = _capture_prompt(monkeypatch)

    async for _ in d_part.generate_response("컨텍스트", "special_case"):
        pass

    assert "지원절차·신청방법·문의처를 쓰지 마세요" in captured[0]


@pytest.mark.asyncio
async def test_unknown_answer_kind_fails_loudly(monkeypatch):
    """오타가 나면 프롬프트 파일을 못 찾아 조용히 이상한 응답이 나가는 대신 즉시 터져야 한다."""
    _capture_prompt(monkeypatch)

    with pytest.raises(ValueError):
        async for _ in d_part.generate_response("컨텍스트", "존재하지_않는_경로"):
            pass
