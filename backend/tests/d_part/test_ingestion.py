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

    assert counts["판례"] == 467  # 중-①소유권변동 임대인지위 승계 판례 재수집 +36 (작업단위 42)
    assert counts["법령원문"] == 932  # 시행령 3종(38) + 민사절차 3법(39) 포함
    assert counts.get("HUG사례집", 0) + counts.get("HUG규정", 0) == 176
    assert counts["정부자료"] == 21  # 깡통전세 유형/예방 8 + 실태조사 섹션 13 (작업단위 37)
    assert counts["생활법령"] == 20  # easylaw 전세사기 피해자 지원 20페이지 (작업단위 40)


@pytest.mark.asyncio
async def test_hug_regulation_gets_topic_tags(ingested):
    """작업단위 48: HUG규정도 enrich 대상이라 키워드 매칭 청크는 topic_tags가 채워진다.
    (topic_tags는 ingest 시점 컬럼이라 임베딩 NULL 상태의 conftest에서도 검증 가능)"""
    with get_engine().connect() as conn:
        n = conn.execute(text(
            "SELECT count(*) FROM d_part_embeddings "
            "WHERE source_type = 'HUG규정' "
            "AND topic_tags IS NOT NULL AND array_length(topic_tags, 1) > 0"
        )).scalar()
    assert n > 0


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
async def test_civil_procedure_statutes_loaded(ingested):
    """일반 민사 절차 법령 — 독촉/강제집행·배당/소액사건 (작업단위 39, C파트와 주제 겹침).

    민사소송법·민사집행법은 발췌 적재라 전문이 아니며, 절차 핵심 조문만 확인한다.
    """
    with get_engine().connect() as conn:
        by_statute = dict(conn.execute(text(
            "SELECT statute_name, count(*) FROM d_part_embeddings"
            " WHERE statute_name IN ('민사소송법', '민사집행법', '소액사건심판법')"
            " GROUP BY statute_name"
        )).all())
        # 대표 조문이 실제로 적재됐는지 (지급명령 신청 / 배당받을 채권자 범위)
        articles = {
            (r.statute_name, r.article_no): r.content
            for r in conn.execute(text(
                "SELECT statute_name, article_no, content FROM d_part_embeddings"
                " WHERE (statute_name = '민사소송법' AND article_no = '464')"
                "    OR (statute_name = '민사집행법' AND article_no = '148')"
            ))
        }

    assert by_statute.get("민사소송법", 0) > 0
    assert by_statute.get("민사집행법", 0) > 0
    assert by_statute.get("소액사건심판법", 0) > 0
    assert "지급명령" in articles[("민사소송법", "464")]
    assert "배당" in articles[("민사집행법", "148")]


@pytest.mark.asyncio
async def test_easylaw_docs_loaded(ingested):
    """상황적용 층 — easylaw 전세사기 생활법령 (작업단위 40).

    페이지=1청크, source_type 생활법령, 통제 어휘 태깅. 신탁 페이지가 전-⑤신탁사기로
    태깅되는지(special_cases RAG 전환 근거)까지 확인.
    """
    with get_engine().connect() as conn:
        rows = {
            r.case_no: r.topic_tags
            for r in conn.execute(text(
                "SELECT case_no, topic_tags FROM d_part_embeddings WHERE source_type = '생활법령'"
            ))
        }
        meta = conn.execute(text(
            "SELECT metadata->>'출처' FROM d_part_embeddings"
            " WHERE source_type = '생활법령' LIMIT 1"
        )).scalar()

    assert len(rows) == 20
    assert "생활법령-1.1.2" in rows  # 신탁 부동산을 이용한 사기
    assert "전-⑤신탁사기" in rows["생활법령-1.1.2"]
    assert meta and "easylaw" in meta  # 출처(공공누리) 표기


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
async def test_ownership_change_precedents_loaded(ingested):
    """중-①소유권_변동모니터링 — 임대인 지위 승계 판례 재수집 (작업단위 42).

    수집 전 0건이던 토픽. --ownership-recollect로 소유권 변동 시 임대인 지위 승계
    (주임법 §3②④) 판례를 추가·태깅해 해소. 오탐(조세/사해행위 등) 6건은 정제 제외.
    """
    with get_engine().connect() as conn:
        docs = conn.execute(text(
            "SELECT count(DISTINCT metadata->>'판례일련번호') FROM d_part_embeddings"
            " WHERE source_type = '판례' AND '중-①소유권_변동모니터링' = ANY(topic_tags)"
        )).scalar_one()

    assert docs == 67  # 신규 승계 판례 36 + 기존 판례 태그 병합 31


@pytest.mark.asyncio
async def test_links_loaded(ingested):
    with get_engine().connect() as conn:
        total = conn.execute(text("SELECT count(*) FROM d_reference_links")).scalar_one()
    assert total == 2490  # 승계 판례 36건의 참조조문 링크 +245 (작업단위 42)


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
