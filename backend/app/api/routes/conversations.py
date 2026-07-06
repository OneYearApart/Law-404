"""
GET /conversations           — 사이드바 대화 목록
GET /conversations/{id}      — 특정 대화 로드
"""
from fastapi import APIRouter, Depends

from app.auth.dependencies import get_current_user
from app.conversations import repository

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/")
async def list_conversations(user=Depends(get_current_user)):
    return await repository.list_conversations(user.id)


@router.get("/{conversation_id}")
async def load_conversation(conversation_id: int, user=Depends(get_current_user)):
    return await repository.load_conversation(conversation_id)
