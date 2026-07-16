"""
공통 로컬 모델 로더 (Ollama 기반 대화 요약 모델 후보).
한국어 성능이 양호하면서 가벼운 모델 조사 중 — 후보 미정.
"""
import asyncio

import httpx

from app.core.config import settings

MAX_RETRIES = 3


async def generate(prompt: str, model: str) -> str:
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=60.0) as client:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.post(
                    "/api/generate", json={"model": model, "prompt": prompt, "stream": False}
                )
                response.raise_for_status()
                return response.json()["response"].strip()
            except httpx.HTTPError:
                if attempt == MAX_RETRIES - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
