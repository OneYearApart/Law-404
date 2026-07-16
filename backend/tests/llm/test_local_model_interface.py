"""
app/local_model/models/common/interface.py::summarize 테스트.
generate(Ollama 호출)는 monkeypatch로 흉내내고, 마크다운/따옴표 벗겨내는 후처리만 검증한다.
"""
import pytest

from app.local_model.models.common import interface


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("**선순위 보증금 확인 필요**", "선순위 보증금 확인 필요"),
        ('"등기부등본 문의"', "등기부등본 문의"),
        ("# 갱신 거절 상담", "갱신 거절 상담"),
        ("일반 채팅 제목", "일반 채팅 제목"),
    ],
)
async def test_summarize_strips_markdown_and_quotes(monkeypatch, raw, expected):
    async def _fake_generate(prompt: str, model: str) -> str:
        return raw

    monkeypatch.setattr(interface, "generate", _fake_generate)

    title = await interface.summarize(["user: 테스트"])

    assert title == expected
