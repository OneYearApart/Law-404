"""
단위 27 — topic_tag 검색의 LIMIT·유사도 재랭킹 회귀 테스트 (실제 DB).

search_by_topic이 판례/HUG를 topic_tags로만 필터해 수십~수백 건을 통째로 컨텍스트에
넣던 문제(토큰 폭증)를 봉쇄했는지 검증한다. 벡터 재랭킹이라 embedding이 채워져 있어야 하고,
conftest.py::ingested가 embed_enabled=False로 임베딩을 날린 직후면 이 테스트는 skip된다.
복구: python -c "import asyncio; from app.rag.ingestion.d_part_ingest import ingest; asyncio.run(ingest(embed_enabled=True))"

embed()는 네트워크를 타지 않도록 고정 벡터로 monkeypatch한다 — 재랭킹 '순서'가 아니라
'상한(top_k)'만 검증하므로 쿼리 벡터 내용은 무관하다.
"""
import pytest
from sqlalchemy import text

from app.core.config import get_engine
from app.graph.parts.d_part.schemas import GENERAL_TOPIC_LABELS
from app.rag.retrievers import d_part as d_part_retriever
from app.rag.retrievers.d_part import (
    _MAX_TOPIC_CONTEXT_CHUNKS,
    _STATUTE_TOP_K,
    _TOPIC_TOP_K,
    DPartRetriever,
)


def _embedding_dim():
    with get_engine().connect() as conn:
        return conn.execute(
            text("SELECT vector_dims(embedding) FROM d_part_embeddings WHERE embedding IS NOT NULL LIMIT 1")
        ).scalar()


@pytest.fixture
def retriever(monkeypatch):
    dim = _embedding_dim()
    if dim is None:
        pytest.skip("d_part_embeddings.embedding이 비어있음 — 임베딩 재적재 후 재실행")

    fixed_vector = [0.1] * dim

    async def _fake_embed(_query: str):
        return fixed_vector

    monkeypatch.setattr(d_part_retriever, "embed", _fake_embed)
    return DPartRetriever()


@pytest.mark.asyncio
@pytest.mark.parametrize("topic_key", list(GENERAL_TOPIC_LABELS))
async def test_search_by_topic_respects_top_k(retriever, topic_key):
    result = await retriever.search_by_topic(topic_key, GENERAL_TOPIC_LABELS[topic_key])

    assert len(result["statute"]) <= _STATUTE_TOP_K
    assert len(result["case_law"]) <= _TOPIC_TOP_K
    assert len(result["cases"]) <= _TOPIC_TOP_K

    total = len(result["statute"]) + len(result["case_law"]) + len(result["cases"])
    assert total <= _MAX_TOPIC_CONTEXT_CHUNKS


@pytest.mark.asyncio
async def test_heavy_tag_is_capped(retriever):
    """중-②근저당_추가설정은 판례 28건이 태깅돼 있어(단위 34 실측) LIMIT가 없으면 28건이
    통째로 반환된다 — 재랭킹+LIMIT로 top_k건까지만 나오는지 확인(캡이 실제로 무는지)."""
    result = await retriever.search_by_topic("중-②근저당_추가설정", "근저당 추가 설정")

    assert len(result["case_law"]) == _TOPIC_TOP_K
