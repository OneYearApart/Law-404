"""
FastAPI 엔트리포인트.
각자 자기 파트 router를 include_router()로 등록하는 한 줄만 추가하면 됩니다.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, conversations, a_part, b_part, c_part, d_part

app = FastAPI(title="주택임대차 법률 챗봇")

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
