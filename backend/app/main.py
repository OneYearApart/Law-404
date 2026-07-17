"""
FastAPI 엔트리포인트.
각자 자기 파트 router를 include_router()로 등록하는 한 줄만 추가하면 됩니다.
"""
from app.api.a_part_errors import APartAPIError, APIErrorBody, APIErrorResponse
from app.api.routes import (
    a_part,
    auth,
    b_part,
    calendar_connections,
    c_part,
    conversations,
    d_part,
)
from app.conversations.errors import ConversationNotFoundError
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="주택임대차 법률 챗봇")


@app.exception_handler(ConversationNotFoundError)
async def conversation_not_found_handler(request: Request, exc: ConversationNotFoundError):
    # 미존재/타인 소유를 구분하지 않고 동일하게 404 — 대화방 존재 여부 유출 방지(IDOR)
    return JSONResponse(status_code=404, content={"detail": "대화방을 찾을 수 없습니다."})

# TODO: 프론트엔드 포트 확정되면 실제 값으로 교체
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(calendar_connections.router)
app.include_router(a_part.router)
app.include_router(b_part.router)

# C파트는 로컬 A파트 테스트에서 임시 제외
# app.include_router(c_part.router)

app.include_router(d_part.router)


@app.exception_handler(APartAPIError)
async def handle_a_part_api_error(request: Request, error: APartAPIError):
    return JSONResponse(
        status_code=error.status_code,
        content=error.response().model_dump(mode="json"),
    )


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(
    request: Request,
    error: RequestValidationError,
):
    if request.url.path.startswith("/chat/a"):
        payload = APIErrorResponse(
            error=APIErrorBody(
                code="REQUEST_VALIDATION_ERROR",
                message="요청 형식이 올바르지 않습니다.",
                retryable=True,
                details={
                    "errors": [
                        {
                            "location": list(item.get("loc", ())),
                            "type": item.get("type"),
                            "message": item.get("msg"),
                        }
                        for item in error.errors()
                    ]
                },
            )
        )
        return JSONResponse(
            status_code=422,
            content=payload.model_dump(mode="json"),
        )
    return await request_validation_exception_handler(request, error)


@app.exception_handler(HTTPException)
async def handle_http_exception(request: Request, error: HTTPException):
    if request.url.path.startswith("/chat/a"):
        code = (
            "AUTHENTICATION_REQUIRED"
            if error.status_code == 401
            else "HTTP_ERROR"
        )
        payload = APIErrorResponse(
            error=APIErrorBody(
                code=code,
                message=str(error.detail),
                retryable=error.status_code >= 500,
            )
        )
        return JSONResponse(
            status_code=error.status_code,
            content=payload.model_dump(mode="json"),
            headers=error.headers,
        )
    return await http_exception_handler(request, error)


@app.get("/health")
async def health():
    return {"status": "ok"}
