"""
FastAPI 엔트리포인트.
각자 자기 파트 router를 include_router()로 등록하는 한 줄만 추가하면 됩니다.
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import auth, conversations, a_part, b_part, c_part, d_part
from app.conversations.errors import ConversationNotFoundError

app = FastAPI(title="주택임대차 법률 챗봇")


@app.exception_handler(ConversationNotFoundError)
async def conversation_not_found_handler(request: Request, exc: ConversationNotFoundError):
    # 미존재/타인 소유를 구분하지 않고 동일하게 404 — 대화방 존재 여부 유출 방지(IDOR)
    return JSONResponse(status_code=404, content={"detail": "대화방을 찾을 수 없습니다."})

# TODO: 프론트엔드 포트 확정되면 실제 값으로 교체
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(a_part.router)
app.include_router(b_part.router)
app.include_router(c_part.router)
app.include_router(d_part.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
