"""
D파트 적재 파이프라인 스모크 테스트.

embed_enabled=False로 실행되므로 embedding 컬럼은 전부 NULL이다 — pgvector 유사도
검색(BaseRetriever.search())은 이 상태에서는 의미가 없어 검증하지 않는다. 대신
스키마/파싱/링크 단계(row count)와, 임베딩 없이도 동작하는 조회 경로
(search_by_requirement의 직접 조문 매칭 + 링크 조인)만 검증한다.
"""
import pytest
from sqlalchemy import text

from app.core.config import get_engine
from app.rag.retrievers.d_part import DPartRetriever


@pytest.mark.asyncio
async def test_row_counts(ingested):
    with get_engine().connect() as conn:
        counts = dict(conn.execute(text(
            "SELECT source_type, count(*) FROM d_part_embeddings GROUP BY source_type"
        )).all())

    assert counts["판례"] == 431
    assert counts["법령원문"] == 703
    assert counts.get("HUG사례집", 0) + counts.get("HUG규정", 0) == 176


@pytest.mark.asyncio
async def test_links_loaded(ingested):
    with get_engine().connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM d_reference_links")).scalar_one()
    assert total == 2220


@pytest.mark.asyncio
async def test_embedding_columns_null_before_embed(ingested):
    with get_engine().connect() as conn:
        remaining = conn.execute(text(
            "SELECT count(*) FROM d_part_embeddings WHERE embedding IS NOT NULL"
        )).scalar_one()
    assert remaining == 0


@pytest.mark.asyncio
async def test_search_by_requirement_returns_valid_chunks(ingested):
    retriever = DPartRetriever()
    result = await retriever.search_by_requirement({
        "moved_in_and_fixed_date": "filled",
        "deposit_under_limit": "filled",
        "multiple_victims": "unclear",
        "no_intent_to_return": None,
    })

    assert {c.article_no for c in result["statute"]} == {"3-①", "3-②"}
    for chunk in result["statute"]:
        assert chunk.statute_name == "전세사기피해자 지원 및 주거안정에 관한 특별법"
        assert chunk.content

    assert isinstance(result["case_law"], list)
    assert isinstance(result["cases"], list)
