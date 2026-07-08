"""
POST /signup, POST /login, POST /logout
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.jwt import create_access_token
from app.auth.login import authenticate_user
from app.auth.models import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
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
from app.core.db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


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
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = authenticate_user(db, req.username, req.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "아이디 또는 비밀번호가 올바르지 않습니다.")
    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=issue_refresh_token(db, user.id),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db: Session = Depends(get_db)):
    """
    refresh token은 매 요청마다 폐기하고 새로 발급한다 (rotation).
    탈취된 refresh token이 재사용되는 것을 막기 위함.
    """
    result = rotate_refresh_token(db, req.refresh_token)
    if result is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "유효하지 않거나 만료된 refresh token입니다.")
    user_id, new_refresh_token = result
    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=new_refresh_token,
    )


@router.post("/logout")
async def logout(req: LogoutRequest, db: Session = Depends(get_db)):
    """
    Access token은 stateless라 서버측에서 즉시 무효화할 수 없다(만료 전까지 유효).
    대신 refresh token은 DB에서 폐기해 재로그인 없이 access token을 재발급받는 것을 막는다.
    """
    revoke_refresh_token(db, req.refresh_token)
    return {"message": "로그아웃되었습니다."}
