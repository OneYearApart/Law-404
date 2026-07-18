"""
B파트 채팅 엔드포인트.
StreamingResponse로 응답하며, 인증된 사용자만 이용 가능하고 대화 이력을 항상 저장합니다.
b파트 담당자만 이 파일을 수정합니다.
"""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.api.events import StreamEvent, EventType
from app.calendar_connections.models import DEFAULT_CALENDAR_PROVIDER
from app.calendar_connections.repository import get_calendar_connection
from app.conversations.repository import (
    get_session_state,
    load_conversation,
    save_message,
    update_session_state,
)
from app.graph.parts.b_part.graph import graph as b_graph
from app.graph.parts.b_part.memory import (
    build_persistable_session_state,
    seed_memory_from_persisted_data,
)
from app.core.db import get_db

router = APIRouter(prefix="/chat/b", tags=["b_part"])


def _parse_db_conversation_id(request: dict) -> int | None:
    """DB 저장용 숫자 conversation_id만 추출합니다."""
    raw_conversation_id = request.get("conversation_id")
    if raw_conversation_id is None:
        return None

    try:
        conversation_id = int(raw_conversation_id)
    except (TypeError, ValueError):
        return None

    if conversation_id <= 0:
        return None
    return conversation_id


def _is_live_smithery_calendar_request(request: dict) -> bool:
    """실제 Smithery Calendar 등록 요청인지 확인합니다."""
    if not isinstance(request.get("pending_action"), dict):
        return False

    mode = str(request.get("calendar_mode", "dry_run")).strip().lower()
    provider = str(
        request.get("calendar_provider", DEFAULT_CALENDAR_PROVIDER)
    ).strip().lower()
    return (
        mode == "live"
        and provider in {"smithery_googlecalendar", "smithery_google_calendar"}
    )


@router.post("/")
async def chat_b(
    request: dict,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conversation_id = _parse_db_conversation_id(request)
    graph_request = dict(request)

    if _is_live_smithery_calendar_request(graph_request):
        provider = str(
            graph_request.get("calendar_provider", DEFAULT_CALENDAR_PROVIDER)
        ).strip().lower()
        connection = get_calendar_connection(
            db,
            user_id=user.id,
            provider=provider,
        )
        if connection is None or connection.status != "connected":
            graph_request["calendar_connection_required"] = True
        else:
            graph_request["calendar_connection_id"] = connection.connection_id

    persisted_state = None
    persisted_messages = []
    if conversation_id is not None:
        persisted_state = await get_session_state(conversation_id, user.id)
        persisted_messages = await load_conversation(conversation_id, user.id)

    async def event_generator():
        yield f"data: {StreamEvent(type=EventType.LOADING).model_dump_json()}\n\n"

        if conversation_id is not None:
            session_id = str(conversation_id)
            seed_memory_from_persisted_data(
                session_id,
                messages=persisted_messages,
                state=persisted_state,
            )
            await save_message(
                user.id,
                "b",
                "user",
                str(graph_request.get("message", graph_request.get("user_input", ""))),
                conversation_id,
            )

        # 판단 단계(전/중/후, 위험신호 감지 등)는 내부적으로 동기 실행
        final_state = await b_graph.ainvoke(graph_request)

        meta_data = {
            "pending_action": final_state.get("pending_action"),
            "calendar_events": final_state.get("calendar_events", []),
            "calendar_registration": final_state.get("calendar_registration"),
            "calendar_tool_result": final_state.get("calendar_tool_result"),
            "memory": final_state.get("memory"),
        }
        yield f"data: {StreamEvent(type=EventType.META, data=meta_data).model_dump_json()}\n\n"

        # 최종 답변만 토큰 단위로 스트리밍
        async for chunk in final_state["response_stream"]:
            yield f"data: {StreamEvent(type=EventType.TOKEN, data=chunk).model_dump_json()}\n\n"

        if conversation_id is not None:
            try:
                await save_message(
                    user.id,
                    "b",
                    "assistant",
                    final_state.get("final_answer", ""),
                    conversation_id,
                )
                await update_session_state(
                    conversation_id,
                    user.id,
                    build_persistable_session_state(
                        str(conversation_id),
                        final_state,
                    ),
                )
            except Exception:
                pass

        yield f"data: {StreamEvent(type=EventType.DONE).model_dump_json()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
