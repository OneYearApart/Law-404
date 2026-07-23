"""
Refresh token 발급/검증/폐기 로직.
- 원문은 클라이언트에만 전달하고 DB에는 SHA256 해시만 저장한다
  (32바이트 랜덤값이라 bcrypt 같은 느린 해시는 불필요 — DB 유출 시 원문 노출만 막으면 됨).
- 매 refresh 요청마다 기존 토큰은 폐기하고 새 토큰을 발급한다 (rotation).
  탈취된 refresh token이 재사용(replay)되는 것을 막기 위함.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.orm import RefreshToken
from app.core.config import settings


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _delete_dead_tokens(db: Session, user_id: int) -> None:
    """만료됐거나 이미 폐기된 토큰을 지운다. 새 토큰 발급 시점마다 호출해 테이블이 무한정 늘어나는 것을 막는다."""
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        or_(
            RefreshToken.expires_at < datetime.now(timezone.utc),
            RefreshToken.revoked_at.isnot(None),
        ),
    ).delete(synchronize_session=False)


def issue_refresh_token(db: Session, user_id: int) -> str:
    _delete_dead_tokens(db, user_id)
    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    db.add(
        RefreshToken(
            user_id=user_id,
            token_hash=_hash_token(raw_token),
            expires_at=expires_at,
        )
    )
    db.commit()
    return raw_token


def rotate_refresh_token(db: Session, raw_token: str) -> tuple[int, str] | None:
    """유효하면 기존 토큰을 폐기하고 새 토큰을 발급해 (user_id, 새 raw_token)을 반환한다."""
    token_row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == _hash_token(raw_token))
        .first()
    )
    if token_row is None or token_row.revoked_at is not None:
        return None
    if token_row.expires_at < datetime.now(timezone.utc):
        return None

    token_row.revoked_at = datetime.now(timezone.utc)
    user_id = token_row.user_id
    db.commit()

    new_raw_token = issue_refresh_token(db, user_id)
    return user_id, new_raw_token


def revoke_refresh_token(db: Session, raw_token: str) -> None:
    token_row = (
        db.query(RefreshToken)
        .filter(RefreshToken.token_hash == _hash_token(raw_token))
        .first()
    )
    if token_row is not None and token_row.revoked_at is None:
        token_row.revoked_at = datetime.now(timezone.utc)
        db.commit()
