"""
D파트 스키마 부트스트랩 fixture.

ingest()가 스키마 생성(CREATE TABLE IF NOT EXISTS)까지 포함하므로, 세션 시작 시
한 번 embed_enabled=False로 전체 파이프라인을 실행해두고 테스트들이 그 결과를 공유한다.
"""
import pytest_asyncio

from app.rag.ingestion.d_part_ingest import ingest


@pytest_asyncio.fixture(scope="session")
async def ingested():
    await ingest(embed_enabled=False)
