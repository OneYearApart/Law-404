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
from app.graph.parts.d_part.schemas import SlotStatus, Stage, VictimRequirementSlots
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
async def test_call_stage_router_live():
    result = await llm_d_part.call_stage_router("계약하려고 준비 중이에요")
    assert result["stage"] in [s.value for s in Stage]


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
    result = await llm_d_part.call_supervisor("보증금을 못 받고 있어요")
    assert isinstance(result.get("category"), str)


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
        "stage": Stage.DURING,
        "stage_confirmed": True,
        "victim_slots": slots,
        "awaiting_relief_confirmation": True,
    }

    result = await graph_module.graph.ainvoke(initial_state)

    assert result["victim_judgment"] is not None
    assert result["response_stream"] is not None
    chunks = [c async for c in result["response_stream"]]
    assert "".join(chunks).strip() != ""
