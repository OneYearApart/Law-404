from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
import psycopg2

load_dotenv(PROJECT_ROOT / "backend" / ".env")
load_dotenv(PROJECT_ROOT / ".env")

REQUIRED_COLLECTIONS = {
    "legal_sources",
    "procedure_sources",
    "safety_guarantee_sources",
    "document_analysis_sources",
}


def run_environment_db() -> dict[str, Any]:
    print("=" * 116)
    print("A파트 환경·DB 검증")
    print("=" * 116)

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY가 없습니다.")
    if not database_url:
        raise RuntimeError("DATABASE_URL이 없습니다.")

    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(), current_user;")
            database, user = cur.fetchone()
            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector';")
            vector_row = cur.fetchone()
            if vector_row is None:
                raise RuntimeError("pgvector 확장이 설치되어 있지 않습니다.")

            cur.execute("SELECT COUNT(*) FROM a_part_rag_documents;")
            row_count = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT collection, COUNT(*)
                FROM a_part_rag_documents
                GROUP BY collection
                ORDER BY collection;
                """
            )
            collections = {name: int(count) for name, count in cur.fetchall()}

    missing = sorted(REQUIRED_COLLECTIONS - set(collections))
    if missing:
        raise RuntimeError(f"필수 collection이 없습니다: {missing}")
    if row_count <= 0:
        raise RuntimeError("a_part_rag_documents가 비어 있습니다.")

    print("DB:", database)
    print("사용자:", user)
    print("pgvector:", vector_row[0])
    print("RAG 행 수:", row_count)
    print("collection:", collections)
    print("최종 판정: PASS")

    return {
        "database": database,
        "user": user,
        "pgvector": vector_row[0],
        "row_count": row_count,
        "collections": collections,
    }


def main() -> None:
    run_environment_db()


if __name__ == "__main__":
    main()
