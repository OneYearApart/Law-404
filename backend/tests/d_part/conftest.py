"""
D파트 스키마 부트스트랩 fixture.

ingest()가 스키마 생성(CREATE TABLE IF NOT EXISTS)까지 포함하므로, 세션 시작 시
한 번 embed_enabled=False로 전체 파이프라인을 실행해두고 테스트들이 그 결과를 공유한다.

⚠️ 임베딩 지뢰 방지: ingest(embed_enabled=False)는 d_part_embeddings를 TRUNCATE 후
embedding=NULL로 재적재한다. 테스트가 공유 dev DB를 대상으로 돌기 때문에, 그대로 두면
pytest를 돌릴 때마다 실서비스 코퍼스의 임베딩이 통째로 날아가 RAG 벡터검색이 죽는다.
그래서 재적재 직전의 임베딩을 content 기준으로 스냅샷해두고, 세션 종료 시 복원한다
(OpenAI 재호출 없이 원상복구). 테스트 자체는 여전히 embedding=NULL 상태에서 돈다.
"""

import pytest_asyncio
from sqlalchemy import text

from app.core.config import get_engine
from app.rag.ingestion.d_part_ingest import ingest


@pytest_asyncio.fixture(scope="session")
async def ingested():
    engine = get_engine()
    with engine.connect() as conn:
        snapshot = [
            {"content": row.content, "emb": row.emb}
            for row in conn.execute(
                text(
                    "SELECT content, embedding::text AS emb FROM d_part_embeddings"
                    " WHERE embedding IS NOT NULL"
                )
            )
        ]

    await ingest(embed_enabled=False)
    try:
        yield
    finally:
        if snapshot:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE d_part_embeddings SET embedding = CAST(:emb AS vector)"
                        " WHERE content = :content AND embedding IS NULL"
                    ),
                    snapshot,
                )
