"""
단위 28 — search_balanced(source_type 쿼터 + distance 임계값) 로직 테스트.

DB/네트워크 없이 self.search와 embed를 monkeypatch해 순수 로직만 검증한다:
(a) source_type별로 쿼터(top_k)만큼 search를 호출하는지, (b) distance가 _MAX_DISTANCE
이상인 청크가 제외되는지, (c) distance 오름차순 정렬.
"""
import pytest

from app.rag.retrievers import d_part as d_part_retriever
from app.rag.retrievers.base import Chunk
from app.rag.retrievers.d_part import _MAX_DISTANCE, _OPEN_QA_QUOTA, DPartRetriever


@pytest.mark.asyncio
async def test_search_balanced_applies_quota_and_distance_threshold(monkeypatch):
    async def _fake_embed(_query: str):
        return [0.1] * 4

    monkeypatch.setattr(d_part_retriever, "embed", _fake_embed)

    calls = []

    async def _fake_search(self, query, top_k=5, grade=None, source_type=None, query_vector=None):
        calls.append((source_type, top_k))
        # 각 source_type에서 top_k건 반환. 첫 건만 임계값 미만, 나머지는 초과 → 필터 확인.
        return [
            Chunk(
                id=i,
                source_type=source_type,
                content=f"{source_type}-{i}",
                distance=(0.3 if i == 0 else _MAX_DISTANCE + 0.1),
            )
            for i in range(top_k)
        ]

    monkeypatch.setattr(DPartRetriever, "search", _fake_search)

    result = await DPartRetriever().search_balanced("질문")

    # (a) 쿼터대로 각 source_type을 해당 top_k로 정확히 호출
    assert dict(calls) == _OPEN_QA_QUOTA
    assert len(calls) == len(_OPEN_QA_QUOTA)
    # (b) distance >= _MAX_DISTANCE는 제외 — source_type별 0.3짜리 1건씩만 생존
    assert len(result) == len(_OPEN_QA_QUOTA)
    assert all(c.distance < _MAX_DISTANCE for c in result)
    # (c) distance 오름차순
    assert [c.distance for c in result] == sorted(c.distance for c in result)


@pytest.mark.asyncio
async def test_search_balanced_returns_empty_when_all_beyond_threshold(monkeypatch):
    async def _fake_embed(_query: str):
        return [0.1] * 4

    monkeypatch.setattr(d_part_retriever, "embed", _fake_embed)

    async def _fake_search(self, query, top_k=5, grade=None, source_type=None, query_vector=None):
        # 전부 임계값 초과 → 전부 필터되어 빈 리스트
        return [
            Chunk(id=i, source_type=source_type, content="x", distance=_MAX_DISTANCE + 0.2)
            for i in range(top_k)
        ]

    monkeypatch.setattr(DPartRetriever, "search", _fake_search)

    result = await DPartRetriever().search_balanced("무관한 질문")
    assert result == []


@pytest.mark.asyncio
async def test_search_balanced_honours_custom_quota(monkeypatch):
    async def _fake_embed(_query: str):
        return [0.1] * 4

    monkeypatch.setattr(d_part_retriever, "embed", _fake_embed)

    calls = []

    async def _fake_search(self, query, top_k=5, grade=None, source_type=None, query_vector=None):
        calls.append((source_type, top_k))
        return [Chunk(id=0, source_type=source_type, content="x", distance=0.3)]

    monkeypatch.setattr(DPartRetriever, "search", _fake_search)

    await DPartRetriever().search_balanced("질문", quota={"법령원문": 3})
    assert calls == [("법령원문", 3)]
