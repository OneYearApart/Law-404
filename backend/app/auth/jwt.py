"""
JWT 토큰 발급/검증.

세션 대신 JWT를 선택한 이유:
- 이 프로젝트는 Redis 등 서버 세션 스토어 없이 Postgres만 프로비저닝되어 있어,
  세션 방식을 쓰려면 별도 스토어 구축 비용이 새로 발생함.
- requirements.txt에 이미 python-jose가 포함되어 있어 팀이 JWT 방향으로
  기울어 있었음.
- A/B/C/D 파트 라우터 + SSE 스트리밍 구조에서 Authorization 헤더 기반
  Bearer 토큰이 상태 없이 일관되게 적용 가능.
  단, 브라우저 네이티브 EventSource는 커스텀 헤더를 못 보내므로, SSE 라우트
  구현 시에는 토큰을 쿼리 파라미터로 넘기거나 fetch 기반 스트리밍이 필요함.

로그아웃은 stateless 방식으로 처리(서버측 토큰 폐기/블랙리스트 없음).
탈취된 토큰이 만료 전까지 유효한 리스크가 있지만, 이를 완화하기 위해
만료 시간을 짧게(1일) 설정했다. 블랙리스트 방식은 추가 저장소와 매 요청
조회 오버헤드가 필요해 현재 MVP 범위에서는 과함.
"""

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"


def create_access_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        return None
