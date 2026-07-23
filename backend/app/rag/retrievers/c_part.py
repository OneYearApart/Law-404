"""
========================================================================
법률 챗봇 카테고리 3 (보증금 반환, 경매배당) Retriever
========================================================================
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import psycopg2
from dotenv import load_dotenv
from openai import OpenAI
from psycopg2.extras import RealDictCursor

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://edu:1234@localhost:5435/edudb")

CATEGORY_ID = 3
EMBEDDING_MODEL = "text-embedding-3-small"


# ========================================================================
# 검색 결과를 표현하는 데이터 구조
# ========================================================================


@dataclass
class RetrievedChunk:
    id: int
    content: str
    similarity: float
    source_type: str  # "statute" | "precedent"
    category_tag: int
    statute_number: Optional[str] = None
    statute_branch: Optional[str] = None
    statute_title: Optional[str] = None
    case_number: Optional[str] = None
    case_name: Optional[str] = None
    case_date: Optional[str] = None
    chunk_type: Optional[str] = None


@dataclass
class RetrievedPrecedent:
    """
    판례 하나를 판시사항/판결요지/판례내용이 합쳐진 형태로 표현.
    (검색 결과를 사용자에게 보여줄 때는 쪼개진 3개보다 이게 더 자연스러움)
    """

    case_number: str
    case_name: str
    case_date: Optional[str]
    max_similarity: float  # 3개 청크 중 가장 높은 유사도
    판시사항: Optional[str] = None
    판결요지: Optional[str] = None
    판례내용: Optional[str] = None


# ========================================================================
# Retriever 본체
# ========================================================================


class CPartRetriever:
    """
    카테고리 3(보증금 반환, 경매배당) 전용 검색기.

    사용 예시:
        retriever = CPartRetriever()
        results = retriever.retrieve("보증금을 못 받고 있어요", top_k=5)
        for r in results:
            print(r.content[:50], r.similarity)
    """

    def __init__(
        self, database_url: str = DATABASE_URL, openai_api_key: str = OPENAI_API_KEY
    ):
        self.database_url = database_url
        self.client = OpenAI(api_key=openai_api_key)
        self.embedding_model = EMBEDDING_MODEL
        logger.info(f"✓ CPartRetriever 초기화 완료 (model={self.embedding_model})")

    # --------------------------------------------------------------
    # 1) 쿼리 임베딩
    # --------------------------------------------------------------
    def _embed_query(self, query: str) -> List[float]:

        response = self.client.embeddings.create(
            model=self.embedding_model,
            input=[query],
        )
        return response.data[0].embedding

    @staticmethod
    def _to_pgvector_literal(embedding: List[float]) -> str:
        """
        Python list를 pgvector가 이해하는 문자열 형태로 변환.
        예: [0.1, 0.2, 0.3] -> "[0.1,0.2,0.3]"
        """
        return "[" + ",".join(str(x) for x in embedding) + "]"

    # --------------------------------------------------------------
    # 2) DB 검색 (raw)
    # --------------------------------------------------------------
    def search(
        self,
        query: str,
        top_k: int = 10,
        source_type: Optional[str] = None,
    ) -> List[RetrievedChunk]:
        """
        질문과 유사한 청크를 top_k개 찾아서 반환합니다. (쪼개진 상태 그대로)

        Args:
            query: 사용자 질문
            top_k: 몇 개까지 가져올지
            source_type: "statute" 또는 "precedent"로 제한하고 싶을 때 (기본: 제한 없음)
        """
        query_embedding = self._embed_query(query)
        embedding_literal = self._to_pgvector_literal(query_embedding)

        sql = """
            SELECT
                id, content, statute_number, statute_branch, statute_title,
                case_number, case_name, case_date, chunk_type, source_type,
                category_tag,
                1 - (embedding <=> %s::vector) AS similarity
            FROM legal_documents_c
            WHERE category_tag = %s
        """
        params: List[Any] = [embedding_literal, CATEGORY_ID]

        if source_type:
            sql += " AND source_type = %s"
            params.append(source_type)

        sql += " ORDER BY embedding <=> %s::vector LIMIT %s"
        params.extend([embedding_literal, top_k])

        conn = psycopg2.connect(self.database_url)
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
        finally:
            conn.close()

        results = [
            RetrievedChunk(
                id=row["id"],
                content=row["content"],
                similarity=float(row["similarity"]),
                source_type=row["source_type"],
                category_tag=row["category_tag"],
                statute_number=row["statute_number"],
                statute_branch=row["statute_branch"],
                statute_title=row["statute_title"],
                case_number=row["case_number"],
                case_name=row["case_name"],
                case_date=str(row["case_date"]) if row["case_date"] else None,
                chunk_type=row["chunk_type"],
            )
            for row in rows
        ]

        logger.info(f"✓ 검색 완료: '{query[:30]}...' → {len(results)}건")
        return results

    # --------------------------------------------------------------
    # 3) 판례 청크 재조립 (판시사항+판결요지+판례내용 -> 판례 1건)
    # --------------------------------------------------------------
    @staticmethod
    def _merge_precedent_chunks(
        chunks: List[RetrievedChunk],
    ) -> List[RetrievedPrecedent]:
        merged: Dict[str, RetrievedPrecedent] = {}

        for chunk in chunks:
            if chunk.source_type != "precedent" or not chunk.case_number:
                continue

            if chunk.case_number not in merged:
                merged[chunk.case_number] = RetrievedPrecedent(
                    case_number=chunk.case_number,
                    case_name=chunk.case_name or "",
                    case_date=chunk.case_date,
                    max_similarity=chunk.similarity,
                )

            precedent = merged[chunk.case_number]
            precedent.max_similarity = max(precedent.max_similarity, chunk.similarity)

            # 판시사항/판결요지/판례내용 중 어디에 넣을지는 chunk_type으로 구분
            if chunk.chunk_type == "판시사항":
                precedent.판시사항 = chunk.content
            elif chunk.chunk_type == "판결요지":
                precedent.판결요지 = chunk.content
            elif chunk.chunk_type == "판례내용":
                precedent.판례내용 = chunk.content

        # 유사도 높은 순서로 정렬
        return sorted(merged.values(), key=lambda p: p.max_similarity, reverse=True)

    # --------------------------------------------------------------
    # 4) 최종 사용자용 인터페이스
    # --------------------------------------------------------------
    def retrieve(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        # 넉넉하게 top_k*3개를 가져온 뒤, 판례는 재조립하면서 자연히 줄어듦
        raw_chunks = self.search(query, top_k=top_k * 3)

        statutes = [c for c in raw_chunks if c.source_type == "statute"][:top_k]
        precedents = self._merge_precedent_chunks(raw_chunks)[:top_k]

        return {
            "statutes": statutes,
            "precedents": precedents,
        }


# ========================================================================
# 빠른 동작 확인용 (python c_part.py 로 직접 실행 가능)
# ========================================================================
if __name__ == "__main__":
    retriever = CPartRetriever()

    test_query = "계약 끝났는데 보증금을 못 받고 있어요"
    result = retriever.retrieve(test_query, top_k=3)

    print(f"\n질문: {test_query}\n")

    print("[관련 조문]")
    for s in result["statutes"]:
        title = f"제{s.statute_number}조" + (
            f"의{s.statute_branch}" if s.statute_branch else ""
        )
        print(f"  - {title} ({s.statute_title}) | 유사도 {s.similarity:.3f}")

    print("\n[관련 판례]")
    for p in result["precedents"]:
        print(f"  - {p.case_name} ({p.case_number}) | 유사도 {p.max_similarity:.3f}")
