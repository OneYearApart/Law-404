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
    assert counts["법령원문"] == 798
    assert counts.get("HUG사례집", 0) + counts.get("HUG규정", 0) == 176
    assert counts["정부자료"] == 21  # 깡통전세 유형/예방 8 + 실태조사 섹션 13 (작업단위 37)


@pytest.mark.asyncio
async def test_decree_articles_loaded(ingested):
    """최우선변제액·소액임차인 범위는 법률 본문이 아닌 시행령에만 있다 (작업단위 38)."""
    with get_engine().connect() as conn:
        rows = dict(conn.execute(text(
            "SELECT article_no, content FROM d_part_embeddings"
            " WHERE statute_name = '주택임대차보호법 시행령' AND article_no IN ('10', '11')"
        )).all())

    assert "5천500만원" in rows["10"]      # 최우선변제 금액 (서울)
    assert "1억6천500만원" in rows["11"]   # 소액임차인 범위 (서울)


@pytest.mark.asyncio
async def test_gov_docs_loaded(ingested):
    """정부자료(깡통전세 유형/예방, 국토부 실태조사) 섹션 청킹 + topic_tags 부여 (작업단위 37)."""
    with get_engine().connect() as conn:
        rows = dict(conn.execute(text(
            "SELECT case_no, topic_tags FROM d_part_embeddings WHERE source_type = '정부자료'"
        )).all())

    # 깡통전세 유형 6종 + 예방법 계약 전/후
    assert {f"깡통전세-유형{i}" for i in range(1, 7)} <= set(rows)
    assert "깡통전세-예방법-계약전" in rows and "깡통전세-예방법-계약후" in rows
    # 신탁사 유형은 통제 어휘 전-⑤신탁사기로 태깅됨
    assert "전-⑤신탁사기" in rows["깡통전세-유형5"]

    # 실태조사 사기유형 분석 하위섹션은 청킹되고, 헤더만 있던 대섹션 조각은 버려짐
    assert "실태조사-Ⅱ-2" in rows
    assert "실태조사-Ⅱ" not in rows  # 표지 한 줄짜리 대섹션 조각 제외


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
