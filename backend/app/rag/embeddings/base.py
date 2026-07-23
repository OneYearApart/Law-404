"""
GPT 임베딩 모델 공통 래퍼 (팀 전체 고정, 파트 분리 없음).
"""

import asyncio

from openai import APIError, AsyncOpenAI, RateLimitError

from app.core.config import settings

MODEL = "text-embedding-3-small"
MAX_RETRIES = 3

_client = AsyncOpenAI(api_key=settings.openai_api_key)


async def embed(text: str) -> list[float]:
    for attempt in range(MAX_RETRIES):
        try:
            response = await _client.embeddings.create(model=MODEL, input=text)
            return response.data[0].embedding
        except (RateLimitError, APIError):
            if attempt == MAX_RETRIES - 1:
                raise
            await asyncio.sleep(2**attempt)


async def embed_batch(texts: list[str], batch_size: int = 100) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        for attempt in range(MAX_RETRIES):
            try:
                response = await _client.embeddings.create(model=MODEL, input=batch)
                embeddings.extend(item.embedding for item in response.data)
                break
            except (RateLimitError, APIError):
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2**attempt)
    return embeddings
