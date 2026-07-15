"""
D파트 검색 전략.

일반 유사도 검색이 아니라, victim_check의 슬롯매핑 결과를 기준으로
조문 + 관련 판례 + 사례집 케이스를 참조조문/주제태그로 링크해서 함께 가져옵니다.
(원문→해설→상황적용 응답 구조 지원 — 기획서 4.3 참고)
"""
from typing import Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text

from app.core.config import get_engine
from app.rag.embeddings.base import embed
from app.rag.retrievers.base import BaseRetriever, Chunk, _vector_literal

JEONSE_LAW_NAME = "전세사기피해자 지원 및 주거안정에 관한 특별법"

# schemas.py의 VictimRequirementSlots 4개 필드는 전세사기피해자법 제3조 "항"이 아니라
# 항① 안의 호(1~4호)로 함께 묶여 있다(statutes_d.py FORCED_SPLIT은 항 단위로만 분리).
# 즉 4개 슬롯 전부 같은 "3-①" 청크를 가리키므로 슬롯별 매핑 없이 항①/② 전체를 반환한다.
JEONSE_LAW_ARTICLE3_HANGS = ["3-①", "3-②"]

_CHUNK_COLUMNS = """id, source_type, statute_name, article_no, case_no,
                   reference_articles, topic_tags, grade, source_date,
                   unresolved_ownership, content, metadata"""

# search_by_topic 컨텍스트 상한. topic_tags 태깅(links_d.py::TOPIC_TAG_KEYWORDS)이 광범위한
# 키워드 기반이라 태그 일치 청크가 판례/HUG 각각 수십~수백 건일 수 있다 → 유사도 상위 top_k만.
_STATUTE_TOP_K = 3
_TOPIC_TOP_K = 3                                        # 판례/HUG사례집 각각
_MAX_TOPIC_CONTEXT_CHUNKS = _STATUTE_TOP_K + _TOPIC_TOP_K + _TOPIC_TOP_K   # = 9

# 단위 28: open_qa(트리 밖 자유질의) 전용 균형 검색. source_type별 쿼터로 한 종류(주로 판례)가
# 컨텍스트를 독점해 조문이 없어도 원문→해설→상황적용을 지어내는 것을 막고, distance 임계값으로
# 무관 문서를 배제한다. _MAX_DISTANCE는 현 코퍼스(1616청크, text-embedding-3-small) 실측 분포로
# 정함: 관련 문서 ~0.36~0.57, 무관 질의("날씨") 0.75+ → 0.65(어휘 갭 여유는 주되 무관은 배제).
_OPEN_QA_QUOTA = {"법령원문": 2, "판례": 2, "HUG사례집": 2, "HUG규정": 1}
_MAX_DISTANCE = 0.65


class DPartRetriever(BaseRetriever):
    def __init__(self):
        super().__init__(table_name="d_part_embeddings")

    async def search(
        self,
        query: str,
        top_k: int = 5,
        grade: Optional[str] = None,
        source_type: Optional[str] = None,
        query_vector: Optional[list[float]] = None,
    ) -> list[Chunk]:
        if query_vector is None:                        # 호출부가 미리 임베딩한 벡터를 넘기면 재임베딩 생략
            query_vector = await embed(query)
        grade_filter = "AND grade = :grade" if grade else ""
        source_type_filter = "AND source_type = :source_type" if source_type else ""
        sql = text(f"""
            SELECT {_CHUNK_COLUMNS},
                   embedding <=> CAST(:query_vector AS vector) AS distance
            FROM {self.table_name}
            WHERE embedding IS NOT NULL
            {grade_filter}
            {source_type_filter}
            ORDER BY distance
            LIMIT :top_k
        """)
        params = {"query_vector": _vector_literal(query_vector), "top_k": top_k}
        if grade:
            params["grade"] = grade
        if source_type:
            params["source_type"] = source_type

        def _query():
            with get_engine().connect() as conn:
                return conn.execute(sql, params).mappings().all()

        rows = await run_in_threadpool(_query)
        return [Chunk(**dict(row)) for row in rows]

    async def search_balanced(
        self, query: str, quota: Optional[dict[str, int]] = None
    ) -> list[Chunk]:
        """open_qa 자유질의 전용 균형 검색. source_type별 쿼터(기본 _OPEN_QA_QUOTA)로
        한 종류가 컨텍스트를 독점하지 않게 하고, distance 임계값(_MAX_DISTANCE)을 넘는
        무관 청크는 제외한다. query는 한 번만 임베딩해 각 source_type 검색에 재사용한다.
        반환이 비면(관련 근거 없음) 호출부(open_qa)가 '근거 없음' 경로로 빠진다."""
        quota = quota or _OPEN_QA_QUOTA
        query_vector = await embed(query)
        merged: list[Chunk] = []
        for source_type, top_k in quota.items():
            merged.extend(await self.search(
                query, top_k=top_k, source_type=source_type, query_vector=query_vector
            ))
        filtered = [c for c in merged if c.distance is not None and c.distance < _MAX_DISTANCE]
        filtered.sort(key=lambda c: c.distance)
        return filtered

    async def search_by_topic(self, topic_key: str, query_text: str) -> dict:
        """일반 시나리오 항목(전/중/후 13개 항목) 키 기준으로 조문 + 판례/HUG사례집을 조회한다.
        판례/HUG는 topic_tags로 후보를 거른 뒤 query_text 유사도로 재랭킹해 상위 top_k만 취한다
        (태그만으로 필터하면 수십~수백 건이 통째로 컨텍스트에 들어가 토큰이 폭증하므로).
        query_text는 한 번만 임베딩해 조문 벡터검색과 두 재랭킹에 재사용한다."""
        query_vector = await embed(query_text)
        statute_chunks = await self.search(
            query_text, top_k=_STATUTE_TOP_K, source_type="법령원문", query_vector=query_vector
        )
        case_law = await self._fetch_by_topic_tag(topic_key, "판례", query_vector)
        cases = await self._fetch_by_topic_tag(topic_key, "HUG사례집", query_vector)
        return {"statute": statute_chunks, "case_law": case_law, "cases": cases}

    async def _fetch_by_topic_tag(
        self, topic_key: str, source_type: str, query_vector: list[float], top_k: int = _TOPIC_TOP_K
    ) -> list[Chunk]:
        """topic_tags에 topic_key가 걸린 청크를 벡터 유사도 순으로 top_k건 반환.
        `&&`(배열 겹침) 파라미터는 psycopg2가 리스트를 잘 어댑팅하지만 의도를 명시하려 text[]로 캐스팅한다."""
        sql = text(f"""
            SELECT {_CHUNK_COLUMNS},
                   embedding <=> CAST(:query_vector AS vector) AS distance
            FROM {self.table_name}
            WHERE source_type = :source_type
              AND topic_tags && CAST(:tags AS text[])
              AND embedding IS NOT NULL
            ORDER BY distance
            LIMIT :top_k
        """)
        params = {
            "query_vector": _vector_literal(query_vector),
            "source_type": source_type,
            "tags": [topic_key],
            "top_k": top_k,
        }

        def _query():
            with get_engine().connect() as conn:
                return conn.execute(sql, params).mappings().all()

        rows = await run_in_threadpool(_query)
        return [Chunk(**dict(row)) for row in rows]

    async def search_by_requirement(self, slot_result: dict) -> dict:
        """요건 슬롯 중 하나라도 평가(충족/불충족/불명확)가 내려졌으면 전세사기피해자법
        제3조(요건 항① + 제외사유 항②) 청크를 조회하고, 링크된 판례/사례집을 함께 붙여 반환한다."""
        slots = slot_result.model_dump() if hasattr(slot_result, "model_dump") else slot_result
        article_nos = JEONSE_LAW_ARTICLE3_HANGS if any(v is not None for v in slots.values()) else []

        statute_chunks = await self._fetch_statute_articles(article_nos)
        case_law = await self._link_related(statute_chunks, source="판례")
        cases = await self._link_related(statute_chunks, source="HUG사례집")
        return {"statute": statute_chunks, "case_law": case_law, "cases": cases}

    async def _fetch_statute_articles(self, article_nos: list[str]) -> list[Chunk]:
        if not article_nos:
            return []
        sql = text(f"""
            SELECT {_CHUNK_COLUMNS}, NULL AS distance
            FROM {self.table_name}
            WHERE statute_name = :statute_name AND article_no = ANY(:article_nos)
        """)

        def _query():
            with get_engine().connect() as conn:
                return conn.execute(
                    sql, {"statute_name": JEONSE_LAW_NAME, "article_nos": article_nos}
                ).mappings().all()

        rows = await run_in_threadpool(_query)
        return [Chunk(**dict(row)) for row in rows]

    async def _link_related(self, chunks: list[Chunk], source: str) -> list[Chunk]:
        """법령원문 청크(chunks)에 링크된 판례, 혹은 그 판례에 다시 링크된 HUG사례집을 조회.

        d_reference_links는 항상 source_type='판례'로 적재되므로(links_d.py), 법령원문 -> 판례는
        역방향 조회(linked_id/linked_statute_name)이고, 법령원문 -> HUG사례집은 판례를 거치는
        2-hop 조회다.
        """
        if not chunks or source not in ("판례", "HUG사례집"):
            return []

        chunk_ids = [c.id for c in chunks]
        statute_names = [c.statute_name for c in chunks if c.statute_name] or [None]

        def _query():
            with get_engine().connect() as conn:
                precedent_ids = conn.execute(text("""
                    SELECT DISTINCT source_id
                    FROM d_reference_links
                    WHERE linked_type = '법령원문'
                      AND (linked_id = ANY(:chunk_ids) OR linked_statute_name = ANY(:statute_names))
                """), {"chunk_ids": chunk_ids, "statute_names": statute_names}).scalars().all()

                if source == "판례":
                    target_ids = list(precedent_ids)
                else:
                    if not precedent_ids:
                        return []
                    target_ids = list(conn.execute(text("""
                        SELECT DISTINCT linked_id
                        FROM d_reference_links
                        WHERE linked_type = 'HUG사례집' AND source_id = ANY(:precedent_ids)
                    """), {"precedent_ids": list(precedent_ids)}).scalars().all())

                if not target_ids:
                    return []

                return conn.execute(text(f"""
                    SELECT {_CHUNK_COLUMNS}, NULL AS distance
                    FROM {self.table_name}
                    WHERE id = ANY(:ids)
                """), {"ids": target_ids}).mappings().all()

        rows = await run_in_threadpool(_query)
        return [Chunk(**dict(row)) for row in rows]
