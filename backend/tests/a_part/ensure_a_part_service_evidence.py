# backend/tests/a_part/ensure_a_part_service_evidence.py
# 최종 서비스 규칙 카드 3건이 JSONL과 DB에 동일하게 존재하는지 확인하고 필요한 카드만 부분 업서트한다.

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from openai import OpenAI
from pgvector.psycopg2 import register_vector


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = PROJECT_ROOT / "backend" / ".env"


@dataclass(frozen=True)
class CardConfig:
    collection: str
    document_id: str
    data_path: Path


CARD_CONFIGS = [
    CardConfig(
        collection="safety_guarantee_sources",
        document_id="law404_payment_recipient_authority_rule_c0001",
        data_path=(
            PROJECT_ROOT
            / "backend/data/a_part/rag/safety_guarantee_source_chunks.jsonl"
        ),
    ),
    CardConfig(
        collection="document_analysis_sources",
        document_id="law404_special_clause_return_rule_c0001",
        data_path=(
            PROJECT_ROOT
            / "backend/data/a_part/rag/document_analysis_source_chunks.jsonl"
        ),
    ),
    CardConfig(
        collection="procedure_sources",
        document_id="law404_household_certificate_timing_rule_c0001",
        data_path=(
            PROJECT_ROOT
            / "backend/data/a_part/rag/procedure_source_chunks.jsonl"
        ),
    ),
]

load_dotenv(ENV_PATH)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://edu:1234@localhost:5433/edudb",
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv(
    "OPENAI_EMBEDDING_MODEL",
    "text-embedding-3-small",
)
EMBEDDING_DIM = int(os.getenv("OPENAI_EMBEDDING_DIM", "1536"))
DATASET_VERSION = os.getenv("RAG_DATASET_VERSION", "law404-rag-v1")


def load_card(config: CardConfig) -> dict:
    if not config.data_path.exists():
        raise RuntimeError(f"JSONL 파일이 없습니다: {config.data_path}")

    matches: list[dict] = []
    for line in config.data_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("chunk_id") == config.document_id:
            matches.append(row)

    if len(matches) != 1:
        raise RuntimeError(
            f"{config.data_path}: {config.document_id} 카드 수가 "
            f"1개가 아닙니다: {len(matches)}"
        )

    row = matches[0]
    if str(row.get("source_type") or "") != "derived_rule":
        raise RuntimeError(
            f"{config.document_id}: source_type이 derived_rule이 아닙니다."
        )
    if not str(row.get("chunk_text") or "").strip():
        raise RuntimeError(f"{config.document_id}: chunk_text가 비어 있습니다.")
    if not row.get("source_document_ids"):
        raise RuntimeError(
            f"{config.document_id}: source_document_ids가 비어 있습니다."
        )
    return row


def main() -> None:
    loaded = [(config, load_card(config)) for config in CARD_CONFIGS]
    stale: list[tuple[CardConfig, dict, str]] = []

    with psycopg2.connect(DATABASE_URL) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            for config, row in loaded:
                cur.execute(
                    """
                    SELECT text, source_type, embedding_model,
                           embedding IS NOT NULL
                    FROM a_part_rag_documents
                    WHERE dataset_version = %s
                      AND collection = %s
                      AND document_id = %s;
                    """,
                    (
                        DATASET_VERSION,
                        config.collection,
                        config.document_id,
                    ),
                )
                saved = cur.fetchone()
                expected_text = str(row.get("chunk_text") or "").strip()

                if not saved:
                    stale.append((config, row, "DB row missing"))
                    continue

                saved_text, source_type, embedding_model, has_embedding = saved
                reasons: list[str] = []
                if str(saved_text or "").strip() != expected_text:
                    reasons.append("text mismatch")
                if source_type != "derived_rule":
                    reasons.append("source_type mismatch")
                if embedding_model != EMBEDDING_MODEL:
                    reasons.append("embedding_model mismatch")
                if not has_embedding:
                    reasons.append("embedding missing")
                if reasons:
                    stale.append((config, row, ", ".join(reasons)))

    if not stale:
        print("최종 서비스 규칙 카드 3건이 이미 최신 상태입니다.")
        print("dataset_version:", DATASET_VERSION)
        print("embedding_model:", EMBEDDING_MODEL)
        for config, _ in loaded:
            print("확인 완료:", config.collection, config.document_id)
        return

    if not OPENAI_API_KEY:
        reasons = "; ".join(
            f"{config.document_id}({reason})"
            for config, _, reason in stale
        )
        raise RuntimeError(
            f"업서트가 필요한 카드가 있지만 OPENAI_API_KEY가 없습니다: {reasons}"
        )

    print("업서트가 필요한 서비스 규칙 카드:")
    for config, _, reason in stale:
        print("-", config.document_id, ":", reason)

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=[
            str(row.get("chunk_text") or "").strip()
            for _, row, _ in stale
        ],
        dimensions=EMBEDDING_DIM,
    )
    if len(response.data) != len(stale):
        raise RuntimeError(
            "임베딩 응답 수가 업서트 대상 카드 수와 다릅니다: "
            f"{len(response.data)} != {len(stale)}"
        )

    sql = """
    INSERT INTO a_part_rag_documents (
        dataset_version,
        collection,
        document_id,
        source_id,
        source_type,
        title,
        text,
        metadata,
        embedding,
        embedding_model,
        updated_at
    ) VALUES (
        %s, %s, %s, %s, %s,
        %s, %s, %s::jsonb, %s, %s, NOW()
    )
    ON CONFLICT (dataset_version, collection, document_id)
    DO UPDATE SET
        source_id = EXCLUDED.source_id,
        source_type = EXCLUDED.source_type,
        title = EXCLUDED.title,
        text = EXCLUDED.text,
        metadata = EXCLUDED.metadata,
        embedding = EXCLUDED.embedding,
        embedding_model = EXCLUDED.embedding_model,
        updated_at = NOW();
    """

    with psycopg2.connect(DATABASE_URL) as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            for index, (config, row, _) in enumerate(stale):
                text = str(row.get("chunk_text") or "").strip()
                cur.execute(
                    sql,
                    (
                        DATASET_VERSION,
                        config.collection,
                        config.document_id,
                        row.get("source_id"),
                        "derived_rule",
                        row.get("source_title") or "",
                        text,
                        json.dumps(row, ensure_ascii=False),
                        response.data[index].embedding,
                        EMBEDDING_MODEL,
                    ),
                )
        conn.commit()

    print("최종 서비스 규칙 카드 부분 업서트 완료")
    print("업서트 수:", len(stale))
    for config, _, _ in stale:
        print("저장 완료:", config.collection, config.document_id)


if __name__ == "__main__":
    main()
