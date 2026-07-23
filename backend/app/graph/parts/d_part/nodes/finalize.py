"""
모든 응답 경로가 수렴하는 마지막 노드.

두 가지를 담당한다(단위 30):
1. 면책 문구를 코드에서 결정론적으로 첨부 — 법률 정보 응답에만 정확히 1회.
   단순 확인질문/재질문/fallthrough에는 붙이지 않는다(disclaimer_required로 노드가 명시).
2. 판단언어 금칙어(단정 표현) 로깅 — 응답을 막지 않고 발생률만 수집(§9.3, MVP).

response_assembly가 이미 response_stream을 채운 턴(victim_judgment 신규 확정)과
general_scenario/open_qa의 LLM 응답은 항상 법률 정보라 면책을 첨부한다. final_answer가
텍스트로 확정된 턴은 disclaimer_required가 True일 때만 첨부한다.
"""

import logging
from typing import AsyncGenerator, AsyncIterator

from app.graph.parts.d_part.nodes._disclaimer import DISCLAIMER
from app.graph.parts.d_part.schemas import DPartGraphState

logger = logging.getLogger(__name__)

_FALLTHROUGH_MESSAGE = "안내드릴 내용이 없습니다. 어떤 점이 궁금하신가요?"

# 종합문서 §9.3 "판단 언어 강제": 응답은 높음/있음/추가확인 3단계만, "됩니다/안됩니다" 류
# 단정 표현 금지. MVP는 응답을 막지 않고(재생성 비용/지연) 위반을 로깅해 발생률만 수집한다.
_BANNED_JUDGMENT_TERMS = (
    "됩니다",
    "확실합니다",
    "틀림없",
    "불가능합니다",
    "보장합니다",
)


def _log_banned_judgment(text: str) -> None:
    found = [t for t in _BANNED_JUDGMENT_TERMS if t in text]
    if found:
        logger.warning("판단언어 금칙어 감지(차단 안 함): %s", found)


async def _stream_text(text: str) -> AsyncGenerator[str, None]:
    yield text


async def _body_only(
    stream: AsyncIterator[str], appendix_text: str | None
) -> AsyncGenerator[str, None]:
    """LLM 응답 스트림을 그대로 흘려보내기만 한다. 첨부 텍스트와 면책은 스트림에 인라인하지 않고
    결정론 슬롯(appendix_text/disclaimer_text)으로 넘겨, 호출부가 별도 UI 블록으로 렌더할 수 있게 한다
    — 프론트가 평문을 정규식으로 쪼개는 걸 막기 위함(값을 아는 쪽이 구조를 준다).

    스트림이라 finalize 시점엔 본문 전체를 알 수 없으므로 소진하며 모아 금칙어를 로깅한다.
    첨부 텍스트는 큐레이션돼 금칙어가 없지만, 방어적으로 로깅 대상에 함께 포함한다."""
    collected = []
    async for token in stream:
        collected.append(token)
        yield token
    if appendix_text:
        collected.append(appendix_text)
    _log_banned_judgment("".join(collected))


async def finalize_response(state: DPartGraphState) -> DPartGraphState:
    # LLM 생성 응답(해설→상황적용) — 항상 법률 정보이므로 면책 필요.
    # 스트림 경로에선 액션플랜·면책을 인라인하지 않고 슬롯으로만 넘긴다. 스트림을 소비하는
    # 호출부(routes/d_part.py)가 본문 뒤에 붙여 messages 저장용 전체 텍스트를 만들고,
    # 동시에 구조화해서 클라이언트로 내보낸다 — 사용자가 보는 것과 저장되는 것은 동일해야 한다.
    if state.get("response_stream") is not None:
        state["response_stream"] = _body_only(
            state["response_stream"], state.get("appendix_text")
        )
        state["disclaimer_text"] = DISCLAIMER
        return state

    # 고정 텍스트 경로: 법률 정보 응답에만 면책, 확인질문/fallthrough엔 붙이지 않는다
    text = state.get("final_answer") or _FALLTHROUGH_MESSAGE
    if state.get("disclaimer_required"):
        _log_banned_judgment(text)
        text = f"{text}\n\n{DISCLAIMER}"
    state["final_answer"] = text
    state["response_stream"] = _stream_text(text)
    return state
