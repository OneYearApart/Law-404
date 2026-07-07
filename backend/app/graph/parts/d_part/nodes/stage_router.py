"""
계약 단계(전/중/후) 1차 판별 노드.
판별 결과는 사용자에게 확인받는 단계를 거칩니다.
"""


async def route_stage(user_input: str) -> str:
    """반환값: '전' | '중' | '후'"""
    raise NotImplementedError
