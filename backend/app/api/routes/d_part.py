"""
D파트 채팅 엔드포인트.
StreamingResponse로 응답하며, 인증된 사용자만 이용 가능하고 대화 이력을 항상 저장합니다.
d파트 담당자만 이 파일을 수정합니다.
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.api.events import StreamEvent, EventType
from app.core.config import settings
from app.conversations.repository import get_session_state, save_message, update_session_state
from app.conversations.summarizer import maybe_summarize_conversation
from app.graph.parts.d_part.graph import graph as d_graph
from app.graph.parts.d_part.nodes._context import build_citation_cards
from app.graph.parts.d_part.schemas import DPartSessionState

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat/d", tags=["d_part"])

_ERROR_MESSAGE = "일시적인 오류로 응답을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."


class DPartChatRequest(BaseModel):
    conversation_id: int
    user_input: str


@router.post("/")
async def chat_d(
    request: DPartChatRequest, background_tasks: BackgroundTasks, user=Depends(get_current_user)
):
    # 소유권 검증은 스트리밍 시작 전에. get_session_state가 타인/미존재 대화방이면
    # ConversationNotFoundError를 던지고, StreamingResponse가 만들어지기 전이므로 404가 정상 반환된다.
    conversation_id = request.conversation_id
    raw_state = await get_session_state(conversation_id, user.id)
    session_state = DPartSessionState.model_validate(raw_state) if raw_state else DPartSessionState()

    async def event_generator():
        yield f"data: {StreamEvent(type=EventType.LOADING).model_dump_json()}\n\n"

        try:
            graph_input = {
                name: getattr(session_state, name) for name in DPartSessionState.model_fields
            } | request.model_dump()

            await save_message(user.id, "d", "user", request.user_input, conversation_id)

            # 판단 단계(전/중/후, 위험신호 감지 등)는 내부적으로 동기 실행
            final_state = await d_graph.ainvoke(graph_input)

            # 근거 카드(조문/판례 verbatim)를 토큰 스트림 앞에 먼저 내보낸다(B파트 META 패턴, 단위 46).
            # retrieved_chunks가 없는 경로(스테이지 확인질문/special_cases/fallback/근거없음)는 emit 안 함.
            cards = build_citation_cards(final_state.get("retrieved_chunks", []))
            if cards:
                yield f"data: {StreamEvent(type=EventType.META, data={'citations': cards}).model_dump_json()}\n\n"

            # 최종 답변만 토큰 단위로 스트리밍. response_assembly가 조립한 응답은 final_answer를
            # 일부러 비워두므로(ainvoke() 반환 dict는 노드가 사후에 채운 값을 반영 못 함) 여기서
            # 청크를 직접 모아 메시지 저장용 전체 텍스트를 만든다.
            chunks = []
            async for chunk in final_state["response_stream"]:
                chunks.append(chunk)
                yield f"data: {StreamEvent(type=EventType.TOKEN, data=chunk).model_dump_json()}\n\n"
            final_answer = final_state.get("final_answer") or "".join(chunks)

            updated_session = DPartSessionState(
                **{name: final_state[name] for name in DPartSessionState.model_fields if name in final_state}
            )
            await update_session_state(conversation_id, user.id, updated_session.model_dump(mode="json"))

            await save_message(user.id, "d", "assistant", final_answer, conversation_id)
            background_tasks.add_task(
                maybe_summarize_conversation, conversation_id, user.id, settings.summary_trigger_turns
            )

            yield f"data: {StreamEvent(type=EventType.DONE).model_dump_json()}\n\n"
        except Exception:
            logger.exception("d_part chat 처리 실패 (conversation_id=%s, user_id=%s)", conversation_id, user.id)
            # 사용자 발화만 남고 응답이 없는 반쪽 레코드를 막기 위해 assistant 에러 안내를 저장한다.
            # (이 저장마저 실패하면 로그만 남기고 error 이벤트는 그대로 내보낸다)
            try:
                await save_message(user.id, "d", "assistant", _ERROR_MESSAGE, conversation_id)
            except Exception:
                logger.exception("에러 placeholder 저장 실패 (conversation_id=%s)", conversation_id)
            yield f"data: {StreamEvent(type=EventType.ERROR, data=_ERROR_MESSAGE).model_dump_json()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", background=background_tasks)
