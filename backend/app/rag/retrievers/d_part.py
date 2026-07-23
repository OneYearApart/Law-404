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
from app.rag.retrievers.d_part_glossary_supplement import SUPPLEMENTARY_GLOSSARY

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
_TOPIC_TOP_K = 3  # 판례/HUG사례집 각각
_MAX_TOPIC_CONTEXT_CHUNKS = _STATUTE_TOP_K + _TOPIC_TOP_K + _TOPIC_TOP_K  # = 9

# 단위 28: open_qa(트리 밖 자유질의) 전용 균형 검색. source_type별 쿼터로 한 종류(주로 판례)가
# 컨텍스트를 독점해 조문이 없어도 원문→해설→상황적용을 지어내는 것을 막고, distance 임계값으로
# 무관 문서를 배제한다. _MAX_DISTANCE는 현 코퍼스(1648청크, text-embedding-3-small) 실측 분포로
# 정함: 관련 문서 ~0.36~0.57, 무관 질의("날씨") 0.75+ → 0.65(어휘 갭 여유는 주되 무관은 배제).
#
# 생활법령·정부자료는 쿼터에 없어서 open_qa가 구조적으로 못 가져오고 있었다. 쿼터를 정할 당시
# 생활법령이 20청크뿐이었는데 이후 52로 늘었고(0d49a39) 쿼터에는 반영되지 않은 것 — 데이터가
# 늘어도 검색 설정이 따라오지 않은 누락이다. 생활법령은 제도를 일반 시민 눈높이로 풀어쓴 층이라
# "이게 뭔가요/어떻게 하나요" 류 자유질의에 가장 잘 맞는데, 같은 질문을 topic 경로(guides를 함께
# 검색한다)로 흘렸을 때와 답변 품질 차이가 크게 났다(임차권등기명령 질의 실측).
_OPEN_QA_QUOTA = {
    "법령원문": 2,
    "판례": 2,
    "HUG사례집": 2,
    "HUG규정": 1,
    "생활법령": 2,
    "정부자료": 1,
}
_MAX_DISTANCE = 0.65

# 용어사전은 HUG규정 안에 Q&A·부록표와 섞여 있어 metadata.항목유형으로만 가려낼 수 있다
# (hug_docs_d.py가 "붙임 2. 용어사전" 구간을 이 태그로 적재).
_GLOSSARY_SOURCE_TYPE = "HUG규정"
_GLOSSARY_ITEM_TYPE = "용어사전"
_glossary_cache: Optional[list[dict]] = None


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
        if query_vector is None:  # 호출부가 미리 임베딩한 벡터를 넘기면 재임베딩 생략
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
            merged.extend(
                await self.search(
                    query,
                    top_k=top_k,
                    source_type=source_type,
                    query_vector=query_vector,
                )
            )
        filtered = [
            c for c in merged if c.distance is not None and c.distance < _MAX_DISTANCE
        ]
        filtered.sort(key=lambda c: c.distance)
        return filtered

    async def search_by_topic(self, topic_key: str, query_text: str) -> dict:
        """일반 시나리오 항목(전/중/후 13개 항목) 키 기준으로 조문 + 판례/HUG사례집/
        생활법령/정부자료/HUG규정을 조회한다. 판례/HUG/생활법령/정부자료는 topic_tags로 후보를 거른 뒤
        query_text 유사도로 재랭킹해 상위 top_k만 취한다(태그만으로 필터하면 수십~수백 건이
        통째로 컨텍스트에 들어가 토큰이 폭증하므로). 생활법령/정부자료/HUG규정(상황적용·해설 층)은 guides로
        함께 반환해 판례/HUG사례집이 0건인 항목(예: 전-④계약서_특약사항)도 근거자료가 검색되게 한다
        (작업단위 40/41 + 코드트랙 재랭킹, HUG규정 편입은 작업단위 48). query_text는 한 번만 임베딩해 재사용한다."""
        query_vector = await embed(query_text)
        statute_chunks = await self.search(
            query_text,
            top_k=_STATUTE_TOP_K,
            source_type="법령원문",
            query_vector=query_vector,
        )
        case_law = await self._fetch_by_topic_tag(topic_key, "판례", query_vector)
        cases = await self._fetch_by_topic_tag(topic_key, "HUG사례집", query_vector)
        guides = (
            await self._fetch_by_topic_tag(topic_key, "생활법령", query_vector)
            + await self._fetch_by_topic_tag(topic_key, "정부자료", query_vector)
            + await self._fetch_by_topic_tag(topic_key, "HUG규정", query_vector)
        )  # 작업단위 48
        return {
            "statute": statute_chunks,
            "case_law": case_law,
            "cases": cases,
            "guides": guides,
        }

    async def _fetch_by_topic_tag(
        self,
        topic_key: str,
        source_type: str,
        query_vector: list[float],
        top_k: int = _TOPIC_TOP_K,
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

    async def search_by_requirement(
        self, slot_result: dict, situation_query: str | None = None
    ) -> dict:
        """요건 슬롯 중 하나라도 평가(충족/불충족/불명확)가 내려졌으면 전세사기피해자법
        제3조(요건 항① + 제외사유 항②) 청크를 조회하고, 링크된 판례/사례집을 함께 붙여 반환한다.
        situation_query(사용자 발화)가 있으면 상황적용 grounding용 생활법령을 벡터 검색해 guides로 붙인다(작업단위 51)."""
        slots = (
            slot_result.model_dump()
            if hasattr(slot_result, "model_dump")
            else slot_result
        )
        article_nos = (
            JEONSE_LAW_ARTICLE3_HANGS
            if any(v is not None for v in slots.values())
            else []
        )

        statute_chunks = await self._fetch_statute_articles(article_nos)
        case_law = await self._link_related(statute_chunks, source="판례")
        cases = await self._link_related(statute_chunks, source="HUG사례집")
        # 상황적용 grounding: 요건 슬롯은 조문 키라 topic_tag가 없으므로 발화로 생활법령을 벡터 검색(작업단위 51)
        guides = (
            await self.search(situation_query, top_k=2, source_type="생활법령")
            if situation_query
            else []
        )
        return {
            "statute": statute_chunks,
            "case_law": case_law,
            "cases": cases,
            "guides": guides,
        }

    async def load_glossary(self) -> list[dict]:
        """HUG 종합안내 "붙임 2. 용어사전"에서 적재된 용어 풀이 전량 + 코드 보충분.

        DB는 인제스천 데이터(약 112건)라 원본 PDF 없이는 못 늘려서, 전세사기 상담에 자주
        나오는 핵심어를 SUPPLEMENTARY_GLOSSARY로 병합한다(표제어 겹치면 DB 우선).

        벡터 검색이 아니라 전량 조회다 — 용어사전은 정적 데이터라 매 턴 DB를 칠 이유가 없어
        프로세스당 1회만 읽고 캐시한다. 인제스천이나 보충분이 바뀌면 재기동이 필요하다.

        content 형식은 hug_docs_d._load_glossary_chunks가 조립한 "{용어}: {설명}\\n예: {예문}" —
        첫 ':'로 표제어와 설명을 가른다. 표제어를 화면에서 제목으로 쓰므로 설명에 다시 남겨두면
        "갑구 / 갑구: 집문서…"로 중복된다. 자르기만 할 뿐 문구는 DB 원문 그대로다.
        형식이 어긋난 행(설명 없이 표제어만)은 풀이로서 쓸모가 없으므로 버린다.
        """
        global _glossary_cache
        if _glossary_cache is not None:
            return _glossary_cache

        sql = text(f"""
            SELECT content
            FROM {self.table_name}
            WHERE source_type = '{_GLOSSARY_SOURCE_TYPE}'
              AND metadata->>'항목유형' = '{_GLOSSARY_ITEM_TYPE}'
        """)

        def _query():
            with get_engine().connect() as conn:
                return conn.execute(sql).mappings().all()

        rows = await run_in_threadpool(_query)
        glossary = []
        for row in rows:
            term, separator, description = (row["content"] or "").partition(":")
            if not separator or not term.strip() or not description.strip():
                continue
            glossary.append({"term": term.strip(), "description": description.strip()})

        # 인제스천으로는 못 늘리는 전세사기 핵심어를 코드 보충분으로 채운다.
        # 표제어가 겹치면 DB 원문을 우선한다(보충분은 새 표제어만 더한다).
        db_terms = {entry["term"] for entry in glossary}
        glossary.extend(
            entry for entry in SUPPLEMENTARY_GLOSSARY if entry["term"] not in db_terms
        )

        _glossary_cache = glossary
        return _glossary_cache

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
                return (
                    conn.execute(
                        sql,
                        {"statute_name": JEONSE_LAW_NAME, "article_nos": article_nos},
                    )
                    .mappings()
                    .all()
                )

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
                precedent_ids = (
                    conn.execute(
                        text("""
                    SELECT DISTINCT source_id
                    FROM d_reference_links
                    WHERE linked_type = '법령원문'
                      AND (linked_id = ANY(:chunk_ids) OR linked_statute_name = ANY(:statute_names))
                """),
                        {"chunk_ids": chunk_ids, "statute_names": statute_names},
                    )
                    .scalars()
                    .all()
                )

                if source == "판례":
                    target_ids = list(precedent_ids)
                else:
                    if not precedent_ids:
                        return []
                    target_ids = list(
                        conn.execute(
                            text("""
                        SELECT DISTINCT linked_id
                        FROM d_reference_links
                        WHERE linked_type = 'HUG사례집' AND source_id = ANY(:precedent_ids)
                    """),
                            {"precedent_ids": list(precedent_ids)},
                        )
                        .scalars()
                        .all()
                    )

                if not target_ids:
                    return []

                return (
                    conn.execute(
                        text(f"""
                    SELECT {_CHUNK_COLUMNS}, NULL AS distance
                    FROM {self.table_name}
                    WHERE id = ANY(:ids)
                """),
                        {"ids": target_ids},
                    )
                    .mappings()
                    .all()
                )

        rows = await run_in_threadpool(_query)
        return [Chunk(**dict(row)) for row in rows]
