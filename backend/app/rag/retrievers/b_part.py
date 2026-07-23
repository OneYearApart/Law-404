"""
B파트 RAG Retriever.

사용자 질문을 임베딩한 뒤 b_part_embeddings 테이블에서
cosine distance 기준으로 관련 법령/판례 청크 Top-K를 검색합니다.

실행 예시:
    python backend/app/rag/retrievers/b_part.py "월세를 50만원에서 60만원으로 올려달라고 합니다."
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.rag.retrievers.base import BaseRetriever

BACKEND_DIR = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_URL = "postgresql://edu:1234@localhost:5435/edudb"
EMBEDDING_MODEL = "text-embedding-3-small"
TABLE_NAME = "b_part_embeddings"


def load_local_env() -> None:
    """python-dotenv 의존성 없이 backend/.env 파일을 읽습니다."""
    env_path = BACKEND_DIR / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_local_env()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


@dataclass
class BPartSearchResult:
    id: int
    source_type: str
    content: str
    metadata: dict[str, Any]
    distance: float
    similarity: float

    @property
    def category(self) -> str:
        return str(self.metadata.get("category", ""))

    @property
    def title(self) -> str:
        return str(self.metadata.get("title", ""))

    @property
    def chunk_type(self) -> str:
        return str(self.metadata.get("chunk_type", ""))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_type": self.source_type,
            "category": self.category,
            "title": self.title,
            "chunk_type": self.chunk_type,
            "content": self.content,
            "metadata": self.metadata,
            "distance": self.distance,
            "similarity": self.similarity,
        }


def format_vector(vector: list[float]) -> str:
    return "[" + ",".join(str(value) for value in vector) + "]"


class BPartQueryEmbedder:
    """사용자 질문을 OpenAI 임베딩 벡터로 변환합니다."""

    def __init__(self, api_key: str = OPENAI_API_KEY, model: str = EMBEDDING_MODEL):
        if not api_key:
            raise ValueError("질문 임베딩을 위해 OPENAI_API_KEY가 필요합니다.")

        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model

    def embed(self, query: str) -> list[float]:
        response = self.client.embeddings.create(model=self.model, input=query)
        return response.data[0].embedding


class BPartRetriever(BaseRetriever):
    def __init__(
        self,
        database_url: str = DATABASE_URL,
        openai_api_key: str = OPENAI_API_KEY,
        table_name: str = TABLE_NAME,
    ):
        super().__init__(table_name=table_name)
        self.database_url = database_url
        self.openai_api_key = openai_api_key
        self.embedder: BPartQueryEmbedder | None = None

    async def search(
        self,
        query: str,
        top_k: int = 5,
        category: str | None = None,
        source_type: str | None = None,
    ) -> list[dict[str, Any]]:
        results = self.search_sync(
            query=query,
            top_k=top_k,
            category=category,
            source_type=source_type,
        )
        return [result.to_dict() for result in results]

    def search_sync(
        self,
        query: str,
        top_k: int = 5,
        category: str | None = None,
        source_type: str | None = None,
    ) -> list[BPartSearchResult]:
        if self.embedder is None:
            self.embedder = BPartQueryEmbedder(api_key=self.openai_api_key)
        query_vector = self.embedder.embed(query)
        return self.search_by_vector(
            query_vector=query_vector,
            top_k=top_k,
            category=category,
            source_type=source_type,
        )

    def search_by_vector(
        self,
        query_vector: list[float],
        top_k: int = 5,
        category: str | None = None,
        source_type: str | None = None,
    ) -> list[BPartSearchResult]:
        import psycopg2

        vector_text = format_vector(query_vector)
        where_clauses = ["embedding IS NOT NULL"]
        params: list[Any] = []

        if category:
            where_clauses.append("metadata->>'category' = %s")
            params.append(category)

        if source_type:
            where_clauses.append("source_type = %s")
            params.append(source_type)

        where_sql = " AND ".join(where_clauses)
        sql = f"""
            SELECT
                id,
                source_type,
                content,
                metadata,
                embedding <=> %s::vector AS distance
            FROM {self.table_name}
            WHERE {where_sql}
            ORDER BY embedding <=> %s::vector
            LIMIT %s
        """

        query_params = [vector_text, *params, vector_text, top_k]
        with psycopg2.connect(self.database_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SET LOCAL ivfflat.probes = 100")
                if category or source_type:
                    cursor.execute("SET LOCAL enable_indexscan = off")
                    cursor.execute("SET LOCAL enable_bitmapscan = off")
                cursor.execute(sql, query_params)
                rows = cursor.fetchall()

        return [self._row_to_result(row) for row in rows]

    def list_categories(self) -> list[dict[str, Any]]:
        import psycopg2

        sql = f"""
            SELECT
                metadata->>'category' AS category,
                COUNT(*) AS count
            FROM {self.table_name}
            GROUP BY metadata->>'category'
            ORDER BY category
        """

        with psycopg2.connect(self.database_url) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()

        return [{"category": row[0], "count": int(row[1])} for row in rows]

    @staticmethod
    def _row_to_result(row: tuple[Any, ...]) -> BPartSearchResult:
        row_id, source_type, content, metadata, distance = row
        distance_value = float(distance)
        similarity = 1.0 - distance_value
        return BPartSearchResult(
            id=int(row_id),
            source_type=str(source_type),
            content=str(content),
            metadata=dict(metadata or {}),
            distance=distance_value,
            similarity=similarity,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="B파트 PGVector 검색 테스트")
    parser.add_argument("query", nargs="?", help="검색할 사용자 질문")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--category", default=None)
    parser.add_argument("--source-type", default=None)
    parser.add_argument("--list-categories", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    retriever = BPartRetriever()

    if args.list_categories:
        print(json.dumps(retriever.list_categories(), ensure_ascii=False, indent=2))
        return

    if not args.query:
        raise SystemExit("검색 질문을 입력하거나 --list-categories 옵션을 사용하세요.")

    results = retriever.search_sync(
        query=args.query,
        top_k=args.top_k,
        category=args.category,
        source_type=args.source_type,
    )
    print(
        json.dumps(
            [result.to_dict() for result in results], ensure_ascii=False, indent=2
        )
    )


if __name__ == "__main__":
    main()
