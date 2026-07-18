"""
실제 GPT-4o 호출 라이브 스모크 테스트. 실제 OpenAI 과금이 발생하므로 기본 pytest
실행에는 포함되지 않는다 — RUN_LIVE_TESTS=1 환경변수가 있을 때만 동작.
내용 정확성이 아니라 스키마/타입만 검증한다(모델 응답은 매번 달라질 수 있음).
"""
import os

import pytest
import pytest_asyncio

from app.auth.orm import User
from app.conversations.orm import Conversation, Message
from app.conversations.repository import create_conversation
from app.core.db import SessionLocal
from app.graph.parts.d_part import graph as graph_module
from app.graph.parts.d_part.schemas import (
    GENERAL_TOPIC_LABELS,
    RISK_SIGNALS,
    SPECIAL_CASE_CATEGORIES,
    SlotStatus,
    VictimRequirementSlots,
)
from app.llm import d_part as llm_d_part

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LIVE_TESTS"),
    reason="실제 OpenAI 과금 발생 — RUN_LIVE_TESTS=1로 명시적 실행",
)


@pytest_asyncio.fixture
async def user_id():
    db = SessionLocal()
    user = User(username="test_live_smoke_user", password_hash="x", nickname="test_live_smoke_nick")
    db.add(user)
    db.commit()
    db.refresh(user)
    uid = user.id
    db.close()

    yield uid

    db = SessionLocal()
    conv_ids = [c.id for c in db.query(Conversation).filter(Conversation.user_id == uid).all()]
    db.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
    db.query(Conversation).filter(Conversation.user_id == uid).delete(synchronize_session=False)
    db.query(User).filter(User.id == uid).delete()
    db.commit()
    db.close()


@pytest.mark.asyncio
async def test_call_victim_check_live():
    result = await llm_d_part.call_victim_check(
        "작년에 전입신고랑 확정일자는 받아뒀는데 집주인이 돌려줄 생각이 없어 보여요",
        existing_slots={},
    )
    for key in ("moved_in_and_fixed_date", "deposit_under_limit", "multiple_victims", "no_intent_to_return"):
        assert result[key] in [s.value for s in SlotStatus]
    assert "multiple_victims_reason" in result


@pytest.mark.asyncio
async def test_call_supervisor_live():
    """축별 판별을 실제 모델이 스키마대로 채우는지 — mock은 이상적인 shape를 흉내낼 뿐이라
    모델이 enum 밖의 값이나 "없음" 같은 문자열을 흘리는지는 실호출로만 잡힌다."""
    result = await llm_d_part.call_supervisor("보증금을 못 받고 있어요")

    assert isinstance(result["recognized"], bool)
    assert set(result["risk_signals"]) <= set(RISK_SIGNALS)
    # 해당 없는 축은 키를 아예 빼도록 지시했다 — 빈 문자열/"없음"이 오면 안 된다
    for axis, allowed in (("topic", list(GENERAL_TOPIC_LABELS)),
                          ("special_case", list(SPECIAL_CASE_CATEGORIES))):
        if axis in result:
            assert result[axis] in allowed


# 확인응답 판별은 mock으로는 검증이 불가능하다 — 가짜 응답이 항상 이상적인 "네"로 오기 때문에
# 예전 키워드 매칭의 과탐("그런데요"가 "네"에 부분문자열 매칭)/미탐("옙"을 놓침)이 단위테스트에서
# 전부 통과해버렸다. 실제 모델로 돌려야만 잡히는 종류의 결함이라 여기서 검증한다.
_STAGE_QUESTION = "말씀하신 내용을 보면 '중' 단계로 보입니다. 맞으신가요?"


@pytest.mark.asyncio
@pytest.mark.parametrize("user_input", ["네", "넵", "옙", "ㅇㅇ", "맞아요", "그렇죠", "어 맞아", "y"])
async def test_call_confirmation_live_yes(user_input):
    result = await llm_d_part.call_confirmation(_STAGE_QUESTION, user_input)
    assert result["answer"] == "yes"


@pytest.mark.asyncio
@pytest.mark.parametrize("user_input", ["아니요", "아니에요", "틀렸어요", "아닌데요", "n"])
async def test_call_confirmation_live_no(user_input):
    result = await llm_d_part.call_confirmation(_STAGE_QUESTION, user_input)
    assert result["answer"] == "no"


@pytest.mark.asyncio
@pytest.mark.parametrize("user_input", ["맞긴 한데 좀 애매해요", "아마도요", "잘 모르겠어요", "그건 왜 물어보세요?"])
async def test_call_confirmation_live_unclear(user_input):
    """부분/조건부 긍정과 질문에 답하지 않은 발화는 yes로 삼키면 안 된다."""
    result = await llm_d_part.call_confirmation(_STAGE_QUESTION, user_input)
    assert result["answer"] == "unclear"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_input",
    ["그런데요 보증금이 3억이에요", "문제네요", "언제까지 해야 하나요", "제 상황이 이런데 어떡하죠"],
)
async def test_call_confirmation_live_no_false_positive(user_input):
    """예전 키워드 매칭이 '네'/'아니' 부분문자열로 전부 yes 처리하던 과탐 케이스 —
    구제수단 게이트에서 이 오탐 하나가 실제 피해자를 지원대상에서 부당 제외시킨다."""
    result = await llm_d_part.call_confirmation(_STAGE_QUESTION, user_input)
    assert result["answer"] != "yes"


@pytest.mark.asyncio
async def test_generate_response_live():
    chunks = [c async for c in llm_d_part.generate_response("판단 결과: 높음\n요건 슬롯: 전부 충족")]
    assert len(chunks) > 0
    assert "".join(chunks).strip() != ""


@pytest.mark.asyncio
async def test_full_graph_live_end_to_end(user_id):
    conversation = await create_conversation(user_id, "d")

    slots = VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus.FILLED,
        deposit_under_limit=SlotStatus.FILLED,
        multiple_victims=SlotStatus.FILLED,
        no_intent_to_return=SlotStatus.FILLED,
    )
    initial_state = {
        "user_input": "아니요 없어요",
        "session_id": str(conversation.id),
        "victim_slots": slots,
        "awaiting_relief_confirmation": True,
    }

    result = await graph_module.graph.ainvoke(initial_state)

    assert result["victim_judgment"] is not None
    assert result["response_stream"] is not None
    chunks = [c async for c in result["response_stream"]]
    assert "".join(chunks).strip() != ""
