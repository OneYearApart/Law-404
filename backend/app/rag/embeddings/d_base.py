"""
D파트 전용 임베딩 배치 래퍼.

embeddings/base.py의 embed_batch()는 batch_size(개수)로만 배치를 나누는데,
청크 하나하나가 8000토큰 이내여도 배치 전체 합이 OpenAI의 요청당 300,000토큰
한도를 넘을 수 있다(D파트 판례 청크처럼 긴 청크가 섞인 경우). 이 문제를 고친
버전이지만 아직 팀과 논의되지 않아 공용 base.py는 건드리지 않고 D파트만 사용한다.
"""
import asyncio

import tiktoken
from openai import APIError, RateLimitError

from app.rag.embeddings.base import MAX_RETRIES, MODEL, _client

MAX_BATCH_TOKENS = 280_000  # OpenAI 요청당 300,000 토큰 한도에 여유를 둔 값
_encoding = tiktoken.get_encoding("cl100k_base")


def _make_batches(texts: list[str], batch_size: int) -> list[list[str]]:
    """개수(batch_size)와 요청당 토큰 총량(MAX_BATCH_TOKENS) 두 제약을 모두 지키도록 배치 구성."""
    batches: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    for t in texts:
        t_tokens = len(_encoding.encode(t))
        if current and (len(current) >= batch_size or current_tokens + t_tokens > MAX_BATCH_TOKENS):
            batches.append(current)
            current, current_tokens = [], 0
        current.append(t)
        current_tokens += t_tokens
    if current:
        batches.append(current)
    return batches


async def embed_batch(texts: list[str], batch_size: int = 100) -> list[list[float]]:
    embeddings: list[list[float]] = []
    for batch in _make_batches(texts, batch_size):
        for attempt in range(MAX_RETRIES):
            try:
                response = await _client.embeddings.create(model=MODEL, input=batch)
                embeddings.extend(item.embedding for item in response.data)
                break
            except (RateLimitError, APIError):
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
    return embeddings
