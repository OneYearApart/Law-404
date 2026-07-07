"""
POST /signup, POST /login, POST /logout
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.jwt import create_access_token
from app.auth.login import authenticate_user
from app.auth.models import LoginRequest, SignupRequest, TokenResponse, UserPublic
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
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/logout")
async def logout():
    """
    Stateless JWT라 서버측 토큰 무효화는 하지 않는다.
    클라이언트가 보관 중인 토큰을 폐기하면 로그아웃이 완료된다.
    """
    return {"message": "로그아웃되었습니다."}
