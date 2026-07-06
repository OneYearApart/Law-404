"""
FastAPI Depends() 용 인증 의존성.

- get_current_user: 로그인 필수 라우터에서 사용
- get_current_user_optional: 비로그인도 허용하되, 로그인 여부에 따라
  저장 로직을 분기하고 싶은 라우터(예: 파트별 chat 엔드포인트)에서 사용
"""


async def get_current_user():
    raise NotImplementedError


async def get_current_user_optional():
    """비로그인이면 None 반환."""
    raise NotImplementedError
