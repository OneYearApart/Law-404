"""
D파트 검색 전략.

일반 유사도 검색이 아니라, victim_check의 슬롯매핑 결과를 기준으로
조문 + 관련 판례 + 사례집 케이스를 참조조문/주제태그로 링크해서 함께 가져옵니다.
(원문→해설→상황적용 응답 구조 지원 — 기획서 4.3 참고)
"""
from typing import Optional

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


class DPartRetriever(BaseRetriever):
    def __init__(self):
        super().__init__(table_name="d_part_embeddings")

    async def search(
        self, query: str, top_k: int = 5, grade: Optional[str] = None, source_type: Optional[str] = None
    ) -> list[Chunk]:
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
        with get_engine().connect() as conn:
            rows = conn.execute(sql, params).mappings().all()
        return [Chunk(**dict(row)) for row in rows]

    async def search_by_topic(self, topic_key: str, query_text: str) -> dict:
        """일반 시나리오 항목(전/중/후 13개 항목) 키 기준으로 조문(벡터검색) + 판례/HUG사례집/
        생활법령/정부자료(topic_tags 직접 매칭)를 조회한다. search_by_requirement와 달리
        조문↔판례 링크(d_reference_links) 없이 각 source_type에 이미 있는 topic_tags를 직접
        필터링한다. 생활법령/정부자료(상황적용·해설 층)를 guides로 함께 반환해 판례/HUG가 0건인
        항목(예: 전-④계약서_특약사항)도 근거자료가 검색되게 한다(작업단위 40/41)."""
        statute_chunks = await self.search(query_text, top_k=3, source_type="법령원문")
        case_law = await self._fetch_by_topic_tag(topic_key, "판례")
        cases = await self._fetch_by_topic_tag(topic_key, "HUG사례집")
        guides = (await self._fetch_by_topic_tag(topic_key, "생활법령")
                  + await self._fetch_by_topic_tag(topic_key, "정부자료"))
        return {"statute": statute_chunks, "case_law": case_law, "cases": cases, "guides": guides}

    async def _fetch_by_topic_tag(self, topic_key: str, source_type: str) -> list[Chunk]:
        sql = text(f"""
            SELECT {_CHUNK_COLUMNS}, NULL AS distance
            FROM {self.table_name}
            WHERE source_type = :source_type AND topic_tags && :tags
        """)
        with get_engine().connect() as conn:
            rows = conn.execute(sql, {"source_type": source_type, "tags": [topic_key]}).mappings().all()
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
        with get_engine().connect() as conn:
            rows = conn.execute(sql, {"statute_name": JEONSE_LAW_NAME, "article_nos": article_nos}).mappings().all()
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

            rows = conn.execute(text(f"""
                SELECT {_CHUNK_COLUMNS}, NULL AS distance
                FROM {self.table_name}
                WHERE id = ANY(:ids)
            """), {"ids": target_ids}).mappings().all()

        return [Chunk(**dict(row)) for row in rows]
