import json
import os
import time
from pathlib import Path
from typing import Any

import psycopg2
import tiktoken
from dotenv import load_dotenv
from openai import OpenAI
from pgvector.psycopg2 import register_vector

PROJECT_ROOT = Path(__file__).resolve().parents[4]
ENV_PATH = PROJECT_ROOT / "backend" / ".env"
DATA_ROOT = PROJECT_ROOT / "backend" / "data" / "a_part" / "rag"

load_dotenv(ENV_PATH)

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://edu:1234@localhost:5435/edudb",
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_MODEL = os.getenv(
    "OPENAI_EMBEDDING_MODEL",
    "text-embedding-3-small",
)
EMBEDDING_DIM = int(os.getenv("OPENAI_EMBEDDING_DIM", "1536"))
DATASET_VERSION = os.getenv("RAG_DATASET_VERSION", "law404-rag-v1")

BATCH_SIZE = int(os.getenv("RAG_EMBEDDING_BATCH_SIZE", "50"))
MAX_CHUNK_TOKENS = int(os.getenv("RAG_MAX_CHUNK_TOKENS", "1200"))
CHUNK_OVERLAP_TOKENS = int(os.getenv("RAG_CHUNK_OVERLAP_TOKENS", "120"))
MAX_RETRIES = int(os.getenv("RAG_EMBEDDING_MAX_RETRIES", "3"))

client = OpenAI(api_key=OPENAI_API_KEY)


def get_token_encoding():
    """현재 임베딩 모델에 맞는 토크나이저를 준비한다."""
    try:
        return tiktoken.encoding_for_model(EMBEDDING_MODEL)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


TOKEN_ENCODING = get_token_encoding()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """JSONL 파일을 한 줄씩 읽고 JSON 객체 목록으로 반환한다."""
    if not path.exists():
        raise FileNotFoundError(f"JSONL 파일이 없습니다: {path}")

    rows: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise RuntimeError(
                    f"JSONL 파싱 실패: {path} line {line_number} / {error}"
                ) from error

            if not isinstance(row, dict):
                raise RuntimeError(f"JSON 객체가 아닙니다: {path} line {line_number}")

            rows.append(row)

    return rows


def convert_legal_row(row: dict[str, Any]) -> dict[str, Any]:
    """법률 카드 한 건을 공통 RAG 문서 구조로 바꾼다."""
    return {
        "collection": "legal_sources",
        "document_id": str(row.get("card_id") or ""),
        "source_id": (
            row.get("law_id")
            or row.get("precedent_id")
            or row.get("interpretation_id")
            or row.get("source_id")
        ),
        "source_type": str(row.get("legal_source_type") or ""),
        "title": (
            row.get("law_name")
            or row.get("case_name")
            or row.get("title")
            or row.get("issue_name")
            or ""
        ),
        "text": str(row.get("card_text") or "").strip(),
        "metadata": dict(row),
    }


def convert_chunk_row(
    collection: str,
    default_source_type: str,
):
    """chunk 기반 데이터셋용 공통 변환 함수를 만든다."""

    def _convert(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "collection": collection,
            "document_id": str(row.get("chunk_id") or ""),
            "source_id": row.get("source_id"),
            "source_type": str(row.get("source_type") or default_source_type),
            "title": str(row.get("source_title") or ""),
            "text": str(row.get("chunk_text") or "").strip(),
            "metadata": dict(row),
        }

    return _convert


DATASET_CONFIGS = [
    {
        "name": "legal_sources",
        "path": DATA_ROOT / "active_rag_legal_cards.jsonl",
        "converter": convert_legal_row,
    },
    {
        "name": "procedure_sources",
        "path": DATA_ROOT / "procedure_source_chunks.jsonl",
        "converter": convert_chunk_row(
            "procedure_sources",
            "procedure_chunk",
        ),
    },
    {
        "name": "safety_guarantee_sources",
        "path": DATA_ROOT / "safety_guarantee_source_chunks.jsonl",
        "converter": convert_chunk_row(
            "safety_guarantee_sources",
            "safety_guarantee_chunk",
        ),
    },
    {
        "name": "document_analysis_sources",
        "path": DATA_ROOT / "document_analysis_source_chunks.jsonl",
        "converter": convert_chunk_row(
            "document_analysis_sources",
            "document_analysis_chunk",
        ),
    },
]


def split_text_by_tokens(
    text: str,
    max_tokens: int = MAX_CHUNK_TOKENS,
    overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
) -> list[str]:
    """긴 텍스트를 토큰 기준으로 나누되 모든 내용을 보존한다."""
    if max_tokens <= 0:
        raise ValueError("max_tokens는 1 이상이어야 합니다.")

    if overlap_tokens < 0:
        raise ValueError("overlap_tokens는 0 이상이어야 합니다.")

    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens는 max_tokens보다 작아야 합니다.")

    tokens = TOKEN_ENCODING.encode(text)

    if len(tokens) <= max_tokens:
        return [text]

    chunks: list[str] = []
    start = 0

    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunk_text = TOKEN_ENCODING.decode(tokens[start:end]).strip()

        if chunk_text:
            chunks.append(chunk_text)

        if end >= len(tokens):
            break

        start = end - overlap_tokens

    return chunks


def expand_document_for_embedding(
    document: dict[str, Any],
) -> list[dict[str, Any]]:
    """문서가 길면 여러 임베딩 문서로 확장하고 원본 추적값을 남긴다."""
    parent_document_id = document["document_id"]
    text_chunks = split_text_by_tokens(document["text"])
    chunk_count = len(text_chunks)
    expanded_documents: list[dict[str, Any]] = []

    for chunk_index, chunk_text in enumerate(text_chunks, start=1):
        chunk_document = dict(document)
        chunk_metadata = dict(document["metadata"])

        if chunk_count == 1:
            chunk_document_id = parent_document_id
        else:
            chunk_document_id = f"{parent_document_id}__part_{chunk_index:03d}"

        chunk_metadata["parent_document_id"] = parent_document_id
        chunk_metadata["chunk_index"] = chunk_index
        chunk_metadata["chunk_count"] = chunk_count

        chunk_document["document_id"] = chunk_document_id
        chunk_document["text"] = chunk_text
        chunk_document["metadata"] = chunk_metadata
        expanded_documents.append(chunk_document)

    if chunk_count > 1:
        print(
            "긴 문서 분할:",
            f"{document['collection']} / {parent_document_id}",
            f"→ {chunk_count}개",
        )

    return expanded_documents


def load_all_documents() -> list[dict[str, Any]]:
    """4개 JSONL을 읽고 검증한 뒤 최종 임베딩 문서 목록을 만든다."""
    documents: list[dict[str, Any]] = []

    for config in DATASET_CONFIGS:
        rows = read_jsonl(config["path"])
        collection_documents: list[dict[str, Any]] = []

        for row in rows:
            document = config["converter"](row)

            if not document["document_id"]:
                raise RuntimeError(f"document_id 없음: {config['name']}")

            if not document["text"]:
                raise RuntimeError(
                    f"text 빈 값: {config['name']} / {document['document_id']}"
                )

            collection_documents.extend(expand_document_for_embedding(document))

        documents.extend(collection_documents)

        print(
            f"{config['name']} 변환 완료:",
            f"원본 {len(rows)}개",
            f"/ 임베딩 문서 {len(collection_documents)}개",
        )

    return documents


def create_embeddings(texts: list[str]) -> list[list[float]]:
    """텍스트 배치의 임베딩을 생성하고 차원을 검증한다."""
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=texts,
            )

            embeddings = [item.embedding for item in response.data]

            if len(embeddings) != len(texts):
                raise RuntimeError(
                    f"임베딩 개수 불일치: 입력={len(texts)}, 출력={len(embeddings)}"
                )

            for embedding in embeddings:
                if len(embedding) != EMBEDDING_DIM:
                    raise RuntimeError(
                        "embedding 차원 불일치: "
                        f"expected={EMBEDDING_DIM}, "
                        f"actual={len(embedding)}"
                    )

            return embeddings

        except Exception as error:
            last_error = error

            if attempt >= MAX_RETRIES:
                break

            wait_seconds = 3 * attempt
            print(
                "임베딩 요청 재시도:",
                f"attempt={attempt}",
                f"/ {wait_seconds}초 후 재시도",
                f"/ {error}",
            )
            time.sleep(wait_seconds)

    raise RuntimeError(f"임베딩 생성 최종 실패: {last_error}") from last_error


def chunked(
    items: list[dict[str, Any]],
    size: int,
):
    """문서 목록을 일정 크기의 배치로 나눈다."""
    if size <= 0:
        raise ValueError("배치 크기는 1 이상이어야 합니다.")

    for start in range(0, len(items), size):
        yield items[start : start + size]


def get_existing_document_keys(
    conn,
) -> set[tuple[str, str]]:
    """같은 데이터 버전과 임베딩 모델로 이미 적재된 문서를 조회한다."""
    sql = """
    SELECT collection, document_id
    FROM a_part_rag_documents
    WHERE dataset_version = %s
      AND embedding_model = %s;
    """

    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                DATASET_VERSION,
                EMBEDDING_MODEL,
            ),
        )
        rows = cur.fetchall()

    return {(collection, document_id) for collection, document_id in rows}


def upsert_documents(
    conn,
    documents: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> None:
    """문서와 임베딩을 a_part_rag_documents에 저장한다."""
    if len(documents) != len(embeddings):
        raise RuntimeError(
            "문서와 임베딩 개수가 다릅니다: "
            f"documents={len(documents)}, "
            f"embeddings={len(embeddings)}"
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
    )
    VALUES (
        %s, %s, %s, %s, %s,
        %s, %s, %s::jsonb, %s, %s, NOW()
    )
    ON CONFLICT (
        dataset_version,
        collection,
        document_id
    )
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

    with conn.cursor() as cur:
        for document, embedding in zip(
            documents,
            embeddings,
            strict=True,
        ):
            cur.execute(
                sql,
                (
                    DATASET_VERSION,
                    document["collection"],
                    document["document_id"],
                    document.get("source_id"),
                    document.get("source_type"),
                    document.get("title"),
                    document["text"],
                    json.dumps(
                        document["metadata"],
                        ensure_ascii=False,
                    ),
                    embedding,
                    EMBEDDING_MODEL,
                ),
            )


def validate_environment() -> None:
    """실행 전에 환경 변수와 입력 파일을 확인한다."""
    if not OPENAI_API_KEY:
        raise RuntimeError(f"OPENAI_API_KEY가 없습니다. 확인 위치: {ENV_PATH}")

    for config in DATASET_CONFIGS:
        if not config["path"].exists():
            raise FileNotFoundError(f"입력 파일이 없습니다: {config['path']}")


def main() -> None:
    validate_environment()

    documents = load_all_documents()

    print(
        "원본 문서 수:",
        sum(len(read_jsonl(config["path"])) for config in DATASET_CONFIGS),
    )
    print("청킹 후 전체 임베딩 문서 수:", len(documents))

    with psycopg2.connect(DATABASE_URL) as conn:
        register_vector(conn)

        existing_keys = get_existing_document_keys(conn)

        pending_documents = [
            document
            for document in documents
            if (
                document["collection"],
                document["document_id"],
            )
            not in existing_keys
        ]

        print("기존 적재 문서 수:", len(existing_keys))
        print("이번 실행 대상 문서 수:", len(pending_documents))

        if not pending_documents:
            print("추가로 적재할 문서가 없습니다.")
            return

        total_batches = (len(pending_documents) + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_index, batch in enumerate(
            chunked(pending_documents, BATCH_SIZE),
            start=1,
        ):
            try:
                texts = [document["text"] for document in batch]
                embeddings = create_embeddings(texts)
                upsert_documents(conn, batch, embeddings)
                conn.commit()

            except Exception:
                conn.rollback()

                print(
                    "배치 처리 실패:",
                    f"{batch_index}/{total_batches}",
                )

                for item_index, document in enumerate(batch):
                    token_count = len(TOKEN_ENCODING.encode(document["text"]))
                    print(
                        "배치 항목:",
                        f"index={item_index}",
                        f"/ collection={document['collection']}",
                        f"/ document_id={document['document_id']}",
                        f"/ tokens={token_count}",
                    )

                raise

            processed_count = min(
                batch_index * BATCH_SIZE,
                len(pending_documents),
            )

            print(
                "배치 적재 완료:",
                f"{batch_index}/{total_batches}",
                f"/ 이번 실행 누적 {processed_count}",
                f"/ 전체 대상 {len(pending_documents)}",
            )

    print("RAG 문서 임베딩 및 DB 적재 완료")


if __name__ == "__main__":
    main()
