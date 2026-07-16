"""
GPT 임베딩 모델 공통 래퍼 (팀 전체 고정, 파트 분리 없음).
"""


async def embed(text: str) -> list[float]:
    raise NotImplementedError
