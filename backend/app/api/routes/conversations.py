"""
POST /conversations                     — 새 대화 생성
GET /conversations                      — 사이드바 대화 목록
GET /conversations/{id}                 — 특정 대화 로드
POST /conversations/{id}/messages       — 공통 메시지 저장
"""
from fastapi import APIRouter, Depends, status

from app.auth.dependencies import get_current_user
from app.conversations import repository
from app.conversations.models import CreateConversationRequest, CreateMessageRequest

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_conversation(body: CreateConversationRequest, user=Depends(get_current_user)):
    return await repository.create_conversation(user.id, body.part, body.title)


@router.get("/")
async def list_conversations(user=Depends(get_current_user)):
    return await repository.list_conversations(user.id)


@router.get("/{conversation_id}")
async def load_conversation(conversation_id: int, user=Depends(get_current_user)):
    # 소유자가 아니거나 없으면 repository가 ConversationNotFoundError → main.py 핸들러가 404로 매핑
    return await repository.load_conversation(conversation_id, user.id)


@router.post("/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
async def create_message(
    conversation_id: int,
    body: CreateMessageRequest,
    user=Depends(get_current_user),
):
    await repository.save_message(
        user.id,
        body.part,
        body.role,
        body.content.strip(),
        conversation_id,
    )
    return {
        "conversation_id": conversation_id,
        "part": body.part,
        "role": body.role,
        "saved": True,
    }
