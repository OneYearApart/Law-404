"""
POST /signup, POST /login, POST /logout
refresh_token은 바디가 아니라 httpOnly 쿠키로만 주고받는다 (XSS로 인한 탈취 방지).
"""
from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth.jwt import create_access_token
from app.auth.login import authenticate_user
from app.auth.models import (
    LoginRequest,
    SignupRequest,
    TokenResponse,
    UserPublic,
)
from app.auth.refresh import issue_refresh_token, revoke_refresh_token, rotate_refresh_token
from app.auth.signup import (
    NicknameAlreadyExistsError,
    UsernameAlreadyExistsError,
    create_user,
)
from app.core.config import settings
from app.core.db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_COOKIE_PATH = "/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,  # TODO: 배포해서 HTTPS 붙으면 True로 변경
        path=REFRESH_COOKIE_PATH,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
    )


@router.post("/signup", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def signup(req: SignupRequest, db: Session = Depends(get_db)):
    try:
        user = create_user(db, req)
    except UsernameAlreadyExistsError:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 사용 중인 아이디입니다.")
    except NicknameAlreadyExistsError:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 사용 중인 닉네임입니다.")
    return user


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = authenticate_user(db, req.username, req.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "아이디 또는 비밀번호가 올바르지 않습니다.")
    _set_refresh_cookie(response, issue_refresh_token(db, user.id))
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    """
    refresh token은 매 요청마다 폐기하고 새로 발급한다 (rotation).
    탈취된 refresh token이 재사용되는 것을 막기 위함.
    """
    if refresh_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token이 없습니다.")
    result = rotate_refresh_token(db, refresh_token)
    if result is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않거나 만료된 refresh token입니다.")
    user_id, new_refresh_token = result
    _set_refresh_cookie(response, new_refresh_token)
    return TokenResponse(access_token=create_access_token(user_id))


@router.post("/logout")
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
):
    """
    Access token은 stateless라 서버측에서 즉시 무효화할 수 없다(만료 전까지 유효).
    대신 refresh token은 DB에서 폐기해 재로그인 없이 access token을 재발급받는 것을 막는다.
    """
    if refresh_token is not None:
        revoke_refresh_token(db, refresh_token)
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)
    return {"message": "로그아웃되었습니다."}
