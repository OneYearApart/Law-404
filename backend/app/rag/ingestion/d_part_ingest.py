"""
D파트 데이터 적재 스크립트.

소스: docs/d_part/raw/
  - 전세사기피해자법_전문.pdf        (조 단위 청킹)
  - HUG_2025_전세피해지원_사례집.pdf (케이스 Q+A 단위 청킹)
  - HUG_전세피해_예방_종합안내.pdf   (섹션 기준 청킹)
  - 정부자료(깡통전세 유형/피해예방, 국토부 실태조사 보고서)  (유형/섹션 단위 청킹)
  - 판례(law.go.kr API 별도 수집)     (판결요지 우선, 필요시 전문 분리)

적재 대상: d_part_embeddings 테이블 (db/schema/d_part_tables.sql)

embed_enabled=False(기본값)이면 스키마 생성 + 파싱/청킹/DB 적재까지만 실행하고
embedding 컬럼은 NULL로 남긴다 (OpenAI API 키 없이도 검증 가능). 이후 .env에
OPENAI_API_KEY를 설정하고 embed_enabled=True로 재실행하면 임베딩까지 채워진다.
재실행 시마다 기존 데이터를 TRUNCATE하므로 멱등적으로 반복 실행 가능하다.
"""

import json
from pathlib import Path

import tiktoken
from sqlalchemy import text

from app.core.config import get_engine
from app.rag.embeddings.d_base import embed_batch
from app.rag.ingestion.easylaw_docs_d import load_easylaw_chunks
from app.rag.ingestion.gov_docs_d import load_gov_chunks
from app.rag.ingestion.hug_docs_d import load_hug_chunks
from app.rag.ingestion.links_d import build_links, enrich_hug_topic_tags
from app.rag.ingestion.precedents_d import load_precedent_chunks
from app.rag.ingestion.statutes_d import load_statute_chunks
from app.rag.retrievers.base import _vector_literal

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "db" / "schema"

MAX_EMBED_TOKENS = 8000  # OpenAI 임베딩 입력 한도(8192)에 여유를 둔 값
_ENCODING = tiktoken.get_encoding("cl100k_base")


def _split_text_by_tokens(text_value: str, max_tokens: int) -> list[str]:
    """문단(\\n\\n) 경계로 그리디 패킹, 문단 자체가 초과하면 토큰 슬라이스로 강제 분할."""
    pieces: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for para in text_value.split("\n\n"):
        para_tokens = len(_ENCODING.encode(para))
        if para_tokens > max_tokens:
            if current:
                pieces.append("\n\n".join(current))
                current, current_tokens = [], 0
            token_ids = _ENCODING.encode(para)
            for i in range(0, len(token_ids), max_tokens):
                pieces.append(_ENCODING.decode(token_ids[i : i + max_tokens]))
            continue
        if current and current_tokens + para_tokens > max_tokens:
            pieces.append("\n\n".join(current))
            current, current_tokens = [], 0
        current.append(para)
        current_tokens += para_tokens

    if current:
        pieces.append("\n\n".join(current))
    return pieces


def _split_oversized_rows(
    rows: list[dict], max_tokens: int = MAX_EMBED_TOKENS
) -> list[dict]:
    """임베딩 입력 한도를 넘는 청크를 여러 서브청크로 분할 (소스 무관, 사후 처리)."""
    result: list[dict] = []
    for row in rows:
        if len(_ENCODING.encode(row["content"])) <= max_tokens:
            result.append(row)
            continue
        pieces = _split_text_by_tokens(row["content"], max_tokens)
        for seq, piece in enumerate(pieces, start=1):
            result.append(
                {
                    **row,
                    "content": piece,
                    "metadata": {
                        **row["metadata"],
                        "chunk_seq": seq,
                        "chunk_total": len(pieces),
                    },
                }
            )
    return result


_INSERT_CHUNK_SQL = text("""
    INSERT INTO d_part_embeddings
        (source_type, statute_name, article_no, case_no, reference_articles,
         topic_tags, grade, source_date, unresolved_ownership, content, metadata)
    VALUES
        (:source_type, :statute_name, :article_no, :case_no, :reference_articles,
         :topic_tags, :grade, :source_date, :unresolved_ownership, :content, CAST(:metadata AS jsonb))
    RETURNING id
""")

_INSERT_LINK_SQL = text("""
    INSERT INTO d_reference_links
        (source_id, source_type, linked_id, linked_type, linked_statute_name, match_basis)
    VALUES
        (:source_id, :source_type, :linked_id, :linked_type, :linked_statute_name, :match_basis)
""")


def _bootstrap_schema(conn):
    conn.execute(text((SCHEMA_DIR / "00_extension.sql").read_text(encoding="utf-8")))
    conn.execute(text((SCHEMA_DIR / "d_part_tables.sql").read_text(encoding="utf-8")))


def _insert_chunk(conn, chunk: dict) -> int:
    result = conn.execute(
        _INSERT_CHUNK_SQL, {**chunk, "metadata": json.dumps(chunk.get("metadata"))}
    )
    return result.scalar_one()


async def ingest(embed_enabled: bool = False):
    engine = get_engine()

    with engine.begin() as conn:
        _bootstrap_schema(conn)
        conn.execute(
            text("TRUNCATE d_reference_links, d_part_embeddings RESTART IDENTITY")
        )

        rows = (
            load_precedent_chunks()
            + load_statute_chunks()
            + load_hug_chunks()
            + load_gov_chunks()
            + load_easylaw_chunks()
        )
        rows = _split_oversized_rows(rows)
        enrich_hug_topic_tags(
            [
                row
                for row in rows
                if row["source_type"]
                in ("HUG사례집", "HUG규정", "정부자료", "생활법령")
            ]
        )
        for row in rows:
            row["id"] = _insert_chunk(conn, row)

        links = build_links(rows)
        for link in links:
            conn.execute(_INSERT_LINK_SQL, link)

    precedent_n = sum(1 for r in rows if r["source_type"] == "판례")
    statute_n = sum(1 for r in rows if r["source_type"] == "법령원문")
    hug_n = sum(1 for r in rows if r["source_type"] in ("HUG사례집", "HUG규정"))
    gov_n = sum(1 for r in rows if r["source_type"] == "정부자료")
    easylaw_n = sum(1 for r in rows if r["source_type"] == "생활법령")
    print(
        f"청크 {len(rows)}건 적재 (판례 {precedent_n}건, 법령 {statute_n}건, HUG {hug_n}건, "
        f"정부자료 {gov_n}건, 생활법령 {easylaw_n}건)"
    )
    print(f"링크 {len(links)}건 적재")

    if embed_enabled:
        contents = [row["content"] for row in rows]
        embeddings = await embed_batch(contents)
        with engine.begin() as conn:
            for row, vector in zip(rows, embeddings):
                conn.execute(
                    text(
                        "UPDATE d_part_embeddings SET embedding = CAST(:embedding AS vector) WHERE id = :id"
                    ),
                    {"embedding": _vector_literal(vector), "id": row["id"]},
                )
        print(f"임베딩 {len(embeddings)}건 적재")
    else:
        print("embed_enabled=False, 임베딩 컬럼은 NULL로 남김")


if __name__ == "__main__":
    import asyncio

    asyncio.run(ingest())
