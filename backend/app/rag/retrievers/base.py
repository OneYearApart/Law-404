"""
pgvector 검색 공통 인터페이스.
파트별 retriever(a_part.py ~ d_part.py)가 이 클래스를 상속해서 사용합니다.
"""
from datetime import date
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import get_engine
from app.rag.embeddings.base import embed


class Chunk(BaseModel):
    id: int
    source_type: str
    statute_name: Optional[str] = None
    article_no: Optional[str] = None
    case_no: Optional[str] = None
    reference_articles: Optional[list[str]] = None
    topic_tags: Optional[list[str]] = None
    grade: Optional[str] = None
    source_date: Optional[date] = None
    unresolved_ownership: bool = False
    content: str
    metadata: Optional[dict] = None
    distance: Optional[float] = None


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(v) for v in vector) + "]"


class BaseRetriever:
    def __init__(self, table_name: str):
        self.table_name = table_name

    async def search(self, query: str, top_k: int = 5) -> list[Chunk]:
        query_vector = await embed(query)
        sql = text(f"""
            SELECT id, source_type, statute_name, article_no, case_no,
                   reference_articles, topic_tags, grade, source_date,
                   unresolved_ownership, content, metadata,
                   embedding <=> CAST(:query_vector AS vector) AS distance
            FROM {self.table_name}
            WHERE embedding IS NOT NULL
            ORDER BY distance
            LIMIT :top_k
        """)
        with get_engine().connect() as conn:
            rows = conn.execute(sql, {"query_vector": _vector_literal(query_vector), "top_k": top_k}).mappings().all()
        return [Chunk(**dict(row)) for row in rows]
