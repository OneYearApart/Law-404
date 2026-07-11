"""
회원가입 로직.
- 아이디, 닉네임 모두 중복 불허 (유니크 제약)
- 비밀번호 해싱 (bcrypt)
"""
from passlib.context import CryptContext
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.models import SignupRequest
from app.auth.orm import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class UsernameAlreadyExistsError(Exception):
    pass


class NicknameAlreadyExistsError(Exception):
    pass


def create_user(db: Session, req: SignupRequest) -> User:
    existing = (
        db.query(User)
        .filter(or_(User.username == req.username, User.nickname == req.nickname))
        .first()
    )
    if existing is not None:
        if existing.username == req.username:
            raise UsernameAlreadyExistsError(req.username)
        raise NicknameAlreadyExistsError(req.nickname)

    user = User(
        username=req.username,
        nickname=req.nickname,
        password_hash=pwd_context.hash(req.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
