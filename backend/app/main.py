"""
FastAPI 엔트리포인트.
각자 자기 파트 router를 include_router()로 등록하는 한 줄만 추가하면 됩니다.
"""
from fastapi import FastAPI

from app.api.routes import auth, conversations, a_part, b_part, c_part, d_part

app = FastAPI(title="주택임대차 법률 챗봇")

app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(a_part.router)
app.include_router(b_part.router)
app.include_router(c_part.router)
app.include_router(d_part.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
