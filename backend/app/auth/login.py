"""
로그인 로직.
- username으로 사용자 조회 후 비밀번호 검증
"""

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.auth.orm import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).first()
    if user is None or not pwd_context.verify(password, user.password_hash):
        return None
    return user
