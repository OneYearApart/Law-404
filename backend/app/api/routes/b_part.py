"""
B파트 채팅 엔드포인트.
StreamingResponse로 응답하며, 로그인 사용자만 대화 이력을 저장합니다.
b파트 담당자만 이 파일을 수정합니다.
"""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.auth.dependencies import get_current_user_optional
from app.api.events import StreamEvent, EventType
from app.conversations.repository import save_message
from app.graph.parts.b_part.graph import graph as b_graph

router = APIRouter(prefix="/chat/b", tags=["b_part"])


@router.post("/")
async def chat_b(request: dict, user=Depends(get_current_user_optional)):
    async def event_generator():
        yield f"data: {StreamEvent(type=EventType.LOADING).model_dump_json()}\n\n"

        # 판단 단계(전/중/후, 위험신호 감지 등)는 내부적으로 동기 실행
        final_state = await b_graph.ainvoke(request)

        # 최종 답변만 토큰 단위로 스트리밍
        async for chunk in final_state["response_stream"]:
            yield f"data: {StreamEvent(type=EventType.TOKEN, data=chunk).model_dump_json()}\n\n"

        if user:
            await save_message(user.id, "b", "assistant", final_state.get("final_answer", ""))

        yield f"data: {StreamEvent(type=EventType.DONE).model_dump_json()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
