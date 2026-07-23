"""
B파트 RAG 데이터 적재 파이프라인.

이 모듈은 B파트 데이터 처리 흐름을 담당합니다.
1. 수집된 법령/판례 JSON 파일을 로드합니다.
2. 법령과 판례를 검색에 적합한 단위로 청킹합니다.
3. OpenAI 임베딩을 생성합니다.
4. PostgreSQL + PGVector에 청크를 적재합니다.

실행 예시:
    python -m app.rag.ingestion.b_part_ingest --dry-run
    python -m app.rag.ingestion.b_part_ingest
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 초기 설정
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[3]
B_PART_DATA_DIR = BACKEND_DIR / "data" / "b_part"
DEFAULT_STATUTE_PATH = B_PART_DATA_DIR / "statutes_contract_period.json"
DEFAULT_PRECEDENT_PATH = B_PART_DATA_DIR / "precedents_selected_contract_period3.json"
DEFAULT_CHUNK_OUTPUT = B_PART_DATA_DIR / "knowledge_base_chunked.jsonl"
DEFAULT_SUMMARY_OUTPUT = B_PART_DATA_DIR / "knowledge_base_chunked_summary.json"

DEFAULT_DATABASE_URL = "postgresql://edu:1234@localhost:5433/edudb"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536
DEFAULT_BATCH_SIZE = 50
DEFAULT_MAX_CHARS = 1500
DEFAULT_OVERLAP_CHARS = 150
DATASET_VERSION = "b_part_chunked_v1"
TABLE_NAME = "b_part_embeddings"

B_PART_CATEGORY_KEYWORDS = {
    "계약갱신": ["계약갱신", "갱신", "재계약", "계약기간", "만료", "연장"],
    "계약갱신요구권": ["계약갱신요구", "갱신요구", "갱신거절", "실거주"],
    "묵시적갱신": ["묵시적", "자동연장", "계약해지 통지"],
    "차임증감": ["차임", "월세", "보증금", "증액", "감액", "5%"],
    "전월세전환": ["전월세전환", "전환율", "월차임", "환산"],
    "임대인의무": ["임대인", "의무", "사용", "수익", "목적물"],
    "수선의무": ["수선", "수리", "하자", "보일러", "누수", "배관", "곰팡이"],
    "계약해지": ["해지", "중도해지", "연체", "해제"],
    "손해배상": ["손해배상", "손해", "배상", "책임"],
}

STATUTE_CATEGORY_RULES = {
    "주택임대차보호법": {
        "4": "계약갱신",
        "6": "계약갱신",
        "6의2": "묵시적갱신",
        "6의3": "계약갱신요구권",
        "7": "차임증감",
        "7의2": "전월세전환",
        "10": "계약갱신",
    },
    "주택임대차보호법 시행령": {
        "8": "차임증감",
        "9": "전월세전환",
    },
    "민법": {
        "618": "임대인의무",
        "623": "임대인의무",
        "624": "임대인의무",
        "625": "손해배상",
        "626": "수선의무",
        "627": "계약해지",
        "628": "차임증감",
        "635": "계약해지",
        "640": "계약해지",
        "654": "계약해지",
    },
}

SECTION_LABELS = {
    "판시사항": "holding",
    "판결요지": "summary",
    "판례내용": "body",
}


@dataclass
class LegalChunk:
    chunk_id: str
    content: str
    source_type: str
    category: str
    title: str
    keywords: list[str]
    metadata: dict[str, Any]
    embedding: list[float] | None = None

    def to_jsonl_row(self) -> dict[str, Any]:
        return {
            "id": self.chunk_id,
            "category": self.category,
            "source_type": self.source_type,
            "title": self.title,
            "content": self.content,
            "keywords": self.keywords,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# 공통 유틸 함수
# ---------------------------------------------------------------------------


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


def read_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    text = str(value)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("\\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_id_part(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^0-9A-Za-z가-힣_의]+", "", text)
    return text or "unknown"


def extract_first_number(value: Any) -> str:
    match = re.search(r"\d+", clean_text(value))
    return match.group(0) if match else ""


def normalize_article(article: Any, branch: Any) -> str:
    article_text = clean_text(article)
    branch_text = clean_text(branch)
    article_number = extract_first_number(article_text) or article_text
    branch_number = extract_first_number(branch_text)
    if branch_number:
        return f"{article_number}의{branch_number}"
    return article_number


def guess_category(*texts: str, default: str = "기타") -> str:
    merged_text = "\n".join(text for text in texts if text)
    for category, keywords in B_PART_CATEGORY_KEYWORDS.items():
        if any(keyword in merged_text for keyword in keywords):
            return category
    return default


def guess_statute_category(
    law_name: str, article: str, title: str, content: str
) -> str:
    for law_keyword, category_by_article in STATUTE_CATEGORY_RULES.items():
        if law_keyword in law_name and article in category_by_article:
            return category_by_article[article]
    return guess_category(title, content)


def keywords_for_category(category: str) -> list[str]:
    return B_PART_CATEGORY_KEYWORDS.get(category, [])


def split_long_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    paragraphs = [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", text)
        if paragraph.strip()
    ]
    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(split_by_window(paragraph, max_chars, overlap_chars))
            continue

        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current.strip())
            current = paragraph

    if current:
        chunks.append(current.strip())

    return chunks


def split_by_window(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return [chunk for chunk in chunks if chunk]


def write_jsonl(path: Path, chunks: list[LegalChunk]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(chunk.to_jsonl_row(), ensure_ascii=False) + "\n")


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)


def format_vector(vector: list[float]) -> str:
    return "[" + ",".join(str(value) for value in vector) + "]"


# ---------------------------------------------------------------------------
# 1단계. 데이터 로드
# ---------------------------------------------------------------------------

load_local_env()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


class BPartDataLoader:
    def __init__(self, statute_path: Path, precedent_path: Path):
        self.statute_path = statute_path
        self.precedent_path = precedent_path

    def load_statutes(self) -> list[dict[str, Any]]:
        data = read_json(self.statute_path)
        if not isinstance(data, list):
            raise ValueError("B파트 법령 데이터는 JSON 배열이어야 합니다.")
        logger.info("B파트 법령 %s건 로드 완료", len(data))
        return data

    def load_precedents(self) -> list[dict[str, Any]]:
        data = read_json(self.precedent_path)
        if not isinstance(data, list):
            raise ValueError("B파트 판례 데이터는 JSON 배열이어야 합니다.")
        logger.info("B파트 판례 %s건 로드 완료", len(data))
        return data


# ---------------------------------------------------------------------------
# 2단계. 청킹
# ---------------------------------------------------------------------------


class StatuteChunker:
    """법령을 조문/항 단위로 나누고, 너무 긴 항은 추가 분할합니다."""

    clause_pattern = re.compile(r"(?=(?:^|\n)\s*[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])")

    def __init__(
        self,
        max_chars: int = DEFAULT_MAX_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    ):
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk_statutes(self, statute_data: list[dict[str, Any]]) -> list[LegalChunk]:
        chunks: list[LegalChunk] = []
        for statute_index, item in enumerate(statute_data, start=1):
            chunks.extend(self._chunk_statute(item, statute_index))
        logger.info("법령 청크 %s개 생성 완료", len(chunks))
        return chunks

    def _chunk_statute(
        self, item: dict[str, Any], statute_index: int
    ) -> list[LegalChunk]:
        law_name = clean_text(item.get("law_name"))
        article = normalize_article(item.get("article"), item.get("branch"))
        title = clean_text(item.get("title"))
        content = clean_text(item.get("content"))
        category = guess_statute_category(law_name, article, title, content)
        statute_title = f"{law_name} 제{article}조 {title}".strip()
        clause_parts = self._split_by_clause(content)
        chunks: list[LegalChunk] = []

        for clause_index, clause_text in enumerate(clause_parts, start=1):
            clause_label = self._extract_clause_label(clause_text) or str(clause_index)
            sub_chunks = split_long_text(
                clause_text, self.max_chars, self.overlap_chars
            )

            for sub_index, sub_text in enumerate(sub_chunks, start=1):
                chunk_id = (
                    f"b_statute_{statute_index:04d}_"
                    f"article_{normalize_id_part(article)}_"
                    f"clauseidx_{clause_index:02d}_"
                    f"clause_{normalize_id_part(clause_label)}_"
                    f"part_{sub_index:02d}"
                )
                content_prefix = f"[{statute_title} / {category} / {clause_label}]"
                chunk_content = f"{content_prefix}\n{sub_text}".strip()
                metadata = {
                    "chunk_id": chunk_id,
                    "document_type": "statute",
                    "category": category,
                    "title": statute_title,
                    "keywords": keywords_for_category(category),
                    "law_name": law_name,
                    "article": article,
                    "branch": clean_text(item.get("branch")),
                    "original_title": title,
                    "chunk_type": "clause",
                    "clause": clause_label,
                    "clause_index": clause_index,
                    "chunk_index": sub_index,
                    "dataset_version": DATASET_VERSION,
                }
                chunks.append(
                    LegalChunk(
                        chunk_id=chunk_id,
                        content=chunk_content,
                        source_type="law",
                        category=category,
                        title=statute_title,
                        keywords=keywords_for_category(category),
                        metadata=metadata,
                    )
                )

        return chunks

    def _split_by_clause(self, content: str) -> list[str]:
        parts = [
            part.strip() for part in self.clause_pattern.split(content) if part.strip()
        ]
        if not parts:
            return [content] if content else []

        if len(parts) > 1 and not self._extract_clause_label(parts[0]):
            heading = parts[0]
            clause_parts = parts[1:]
            clause_parts[0] = f"{heading}\n{clause_parts[0]}".strip()
            return clause_parts

        return parts

    @staticmethod
    def _extract_clause_label(text: str) -> str:
        match = re.match(r"\s*([①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])", text)
        return match.group(1) if match else ""


class PrecedentChunker:
    """판례를 판시사항, 판결요지, 판례내용 단위로 나눕니다."""

    section_pattern = re.compile(r"(판시사항|판결요지|판례내용)\s*:", re.MULTILINE)

    def __init__(
        self,
        max_chars: int = DEFAULT_MAX_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    ):
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk_precedents(
        self, precedent_data: list[dict[str, Any]]
    ) -> list[LegalChunk]:
        chunks: list[LegalChunk] = []
        for precedent_index, item in enumerate(precedent_data, start=1):
            chunks.extend(self._chunk_precedent(item, precedent_index))
        logger.info("판례 청크 %s개 생성 완료", len(chunks))
        return chunks

    def _chunk_precedent(
        self, item: dict[str, Any], precedent_index: int
    ) -> list[LegalChunk]:
        metadata = dict(item.get("metadata") or {})
        page_content = clean_text(item.get("page_content"))
        case_number = (
            clean_text(metadata.get("case_number"))
            or f"precedent_{precedent_index:04d}"
        )
        case_name = clean_text(metadata.get("case_name"))
        decision_date = clean_text(metadata.get("decision_date"))
        category = clean_text(metadata.get("category")) or guess_category(page_content)
        title = self._build_title(case_name, case_number, decision_date)
        sections = self._extract_sections(page_content)
        chunks: list[LegalChunk] = []

        for section_index, (section_name, section_text) in enumerate(sections, start=1):
            chunk_type = SECTION_LABELS.get(section_name, "body")
            sub_chunks = split_long_text(
                section_text, self.max_chars, self.overlap_chars
            )

            for sub_index, sub_text in enumerate(sub_chunks, start=1):
                chunk_id = (
                    f"b_precedent_{precedent_index:04d}_"
                    f"{chunk_type}_"
                    f"part_{sub_index:02d}"
                )
                content_prefix = f"[{title} / {category} / {section_name}]"
                chunk_content = f"{content_prefix}\n{sub_text}".strip()
                chunk_metadata = {
                    **metadata,
                    "chunk_id": chunk_id,
                    "document_type": "precedent",
                    "category": category,
                    "title": title,
                    "keywords": keywords_for_category(category),
                    "case_number": case_number,
                    "case_name": case_name,
                    "decision_date": decision_date,
                    "chunk_type": section_name,
                    "chunk_index": sub_index,
                    "section_index": section_index,
                    "dataset_version": DATASET_VERSION,
                }
                chunks.append(
                    LegalChunk(
                        chunk_id=chunk_id,
                        content=chunk_content,
                        source_type="precedent",
                        category=category,
                        title=title,
                        keywords=keywords_for_category(category),
                        metadata=chunk_metadata,
                    )
                )

        return chunks

    def _extract_sections(self, page_content: str) -> list[tuple[str, str]]:
        matches = list(self.section_pattern.finditer(page_content))
        if not matches:
            return [("판례내용", page_content)] if page_content else []

        sections: list[tuple[str, str]] = []
        for index, match in enumerate(matches):
            section_name = match.group(1)
            start = match.end()
            end = (
                matches[index + 1].start()
                if index + 1 < len(matches)
                else len(page_content)
            )
            section_text = page_content[start:end].strip()
            if section_text:
                sections.append((section_name, section_text))
        return sections

    @staticmethod
    def _build_title(case_name: str, case_number: str, decision_date: str) -> str:
        title_parts = [part for part in [case_name, case_number, decision_date] if part]
        return " ".join(title_parts) if title_parts else "판례"


# ---------------------------------------------------------------------------
# 3단계. 임베딩 생성
# ---------------------------------------------------------------------------


class EmbeddingGenerator:
    def __init__(self, api_key: str, model: str = EMBEDDING_MODEL):
        if not api_key:
            raise ValueError("임베딩 생성을 위해 OPENAI_API_KEY가 필요합니다.")
        from openai import OpenAI

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.dimension = EMBEDDING_DIMENSION
        logger.info("임베딩 모델 초기화 완료: %s", self.model)

    def generate_embeddings(
        self, chunks: list[LegalChunk], batch_size: int = DEFAULT_BATCH_SIZE
    ) -> list[LegalChunk]:
        logger.info("임베딩 생성 시작: %s개 청크", len(chunks))

        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            texts = [chunk.content for chunk in batch]

            try:
                response = self.client.embeddings.create(model=self.model, input=texts)
            except Exception:
                logger.exception("임베딩 생성 실패: batch 시작 인덱스 %s", start)
                raise

            for chunk, embedding_data in zip(batch, response.data):
                chunk.embedding = embedding_data.embedding

            logger.info("임베딩 진행 상황: %s/%s", start + len(batch), len(chunks))

        return chunks


# ---------------------------------------------------------------------------
# 4단계. 데이터베이스 적재
# ---------------------------------------------------------------------------


class DatabaseIngestor:
    def __init__(self, database_url: str, table_name: str = TABLE_NAME):
        self.database_url = database_url
        self.table_name = table_name
        self.conn = None

    def connect(self) -> None:
        import psycopg2

        logger.info("PostgreSQL 연결 시작")
        self.conn = psycopg2.connect(self.database_url)

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def create_table(self) -> None:
        if not self.conn:
            raise RuntimeError("DB 연결이 초기화되지 않았습니다.")

        sql = f"""
        CREATE EXTENSION IF NOT EXISTS vector;

        CREATE TABLE IF NOT EXISTS {self.table_name} (
            id SERIAL PRIMARY KEY,
            source_type VARCHAR(50),
            content TEXT NOT NULL,
            metadata JSONB,
            embedding VECTOR({EMBEDDING_DIMENSION})
        );

        CREATE INDEX IF NOT EXISTS {self.table_name}_embedding_idx
            ON {self.table_name}
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);

        CREATE INDEX IF NOT EXISTS {self.table_name}_source_type_idx
            ON {self.table_name} (source_type);

        CREATE INDEX IF NOT EXISTS {self.table_name}_metadata_category_idx
            ON {self.table_name} ((metadata->>'category'));
        """

        with self.conn.cursor() as cursor:
            cursor.execute(sql)
        self.conn.commit()
        logger.info("테이블 및 인덱스 준비 완료: %s", self.table_name)

    def clear_dataset_version(self, dataset_version: str = DATASET_VERSION) -> None:
        if not self.conn:
            raise RuntimeError("DB 연결이 초기화되지 않았습니다.")

        with self.conn.cursor() as cursor:
            cursor.execute(
                f"DELETE FROM {self.table_name} WHERE metadata->>'dataset_version' = %s",
                (dataset_version,),
            )
        self.conn.commit()
        logger.info("기존 데이터 삭제 완료: dataset_version=%s", dataset_version)

    def insert_chunks(self, chunks: list[LegalChunk]) -> int:
        from psycopg2.extras import Json, execute_values

        if not self.conn:
            raise RuntimeError("DB 연결이 초기화되지 않았습니다.")

        rows = []
        for chunk in chunks:
            if chunk.embedding is None:
                raise ValueError(f"청크에 임베딩이 없습니다: {chunk.chunk_id}")

            rows.append(
                (
                    chunk.source_type,
                    chunk.content,
                    Json(chunk.metadata),
                    format_vector(chunk.embedding),
                )
            )

        sql = f"""
            INSERT INTO {self.table_name}
                (source_type, content, metadata, embedding)
            VALUES %s
        """

        with self.conn.cursor() as cursor:
            execute_values(cursor, sql, rows, page_size=DEFAULT_BATCH_SIZE)

        self.conn.commit()
        logger.info("청크 적재 완료: %s개", len(rows))
        return len(rows)


# ---------------------------------------------------------------------------
# 5단계. 파이프라인 조율
# ---------------------------------------------------------------------------


class BPartRAGPipeline:
    def __init__(
        self,
        statute_path: Path = DEFAULT_STATUTE_PATH,
        precedent_path: Path = DEFAULT_PRECEDENT_PATH,
        chunk_output_path: Path = DEFAULT_CHUNK_OUTPUT,
        summary_output_path: Path = DEFAULT_SUMMARY_OUTPUT,
        database_url: str | None = None,
        openai_api_key: str | None = None,
        dry_run: bool = False,
    ):
        self.statute_path = statute_path
        self.precedent_path = precedent_path
        self.chunk_output_path = chunk_output_path
        self.summary_output_path = summary_output_path
        self.database_url = database_url or os.getenv("DATABASE_URL", DATABASE_URL)
        self.openai_api_key = openai_api_key or os.getenv(
            "OPENAI_API_KEY", OPENAI_API_KEY
        )
        self.dry_run = dry_run

        self.data_loader = BPartDataLoader(statute_path, precedent_path)
        self.statute_chunker = StatuteChunker()
        self.precedent_chunker = PrecedentChunker()

    def run(self) -> dict[str, Any]:
        logger.info("=" * 70)
        logger.info("B파트 RAG 적재 파이프라인 시작")
        logger.info("=" * 70)

        logger.info("[1/5단계] JSON 데이터 로드")
        statutes = self.data_loader.load_statutes()
        precedents = self.data_loader.load_precedents()

        logger.info("[2/5단계] 데이터 청킹")
        statute_chunks = self.statute_chunker.chunk_statutes(statutes)
        precedent_chunks = self.precedent_chunker.chunk_precedents(precedents)
        chunks = statute_chunks + precedent_chunks
        self._validate_unique_chunk_ids(chunks)
        write_jsonl(self.chunk_output_path, chunks)

        summary = self._build_summary(chunks, statutes, precedents)
        write_summary(self.summary_output_path, summary)
        logger.info("청크 파일 생성 완료: %s", self.chunk_output_path)
        logger.info("요약 파일 생성 완료: %s", self.summary_output_path)

        if self.dry_run:
            logger.info(
                "[3/5단계] dry-run 모드입니다. 임베딩 생성과 DB 적재를 건너뜁니다."
            )
            return summary

        logger.info("[3/5단계] 임베딩 생성")
        embedding_generator = EmbeddingGenerator(self.openai_api_key)
        embedded_chunks = embedding_generator.generate_embeddings(chunks)

        logger.info("[4/5단계] PGVector 적재")
        db_ingestor = DatabaseIngestor(self.database_url)
        try:
            db_ingestor.connect()
            db_ingestor.create_table()
            db_ingestor.clear_dataset_version(DATASET_VERSION)
            saved_count = db_ingestor.insert_chunks(embedded_chunks)
        finally:
            db_ingestor.close()

        logger.info("[5/5단계] 파이프라인 완료")
        logger.info("저장된 B파트 청크 수: %s", saved_count)
        summary["saved_count"] = saved_count
        return summary

    def _build_summary(
        self,
        chunks: list[LegalChunk],
        statutes: list[dict[str, Any]],
        precedents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        by_source_type = Counter(chunk.source_type for chunk in chunks)
        by_category = Counter(chunk.category for chunk in chunks)
        by_chunk_type = Counter(
            chunk.metadata.get("chunk_type", "unknown") for chunk in chunks
        )

        return {
            "dataset_version": DATASET_VERSION,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dimension": EMBEDDING_DIMENSION,
            "input": {
                "statute_path": str(self.statute_path),
                "precedent_path": str(self.precedent_path),
                "statute_documents": len(statutes),
                "precedent_documents": len(precedents),
            },
            "output": {
                "jsonl": str(self.chunk_output_path),
                "summary": str(self.summary_output_path),
                "table": TABLE_NAME,
            },
            "total_chunks": len(chunks),
            "by_source_type": dict(sorted(by_source_type.items())),
            "by_category": dict(sorted(by_category.items())),
            "by_chunk_type": dict(sorted(by_chunk_type.items())),
        }

    @staticmethod
    def _validate_unique_chunk_ids(chunks: list[LegalChunk]) -> None:
        counter = Counter(chunk.chunk_id for chunk in chunks)
        duplicates = [chunk_id for chunk_id, count in counter.items() if count > 1]
        if duplicates:
            raise ValueError(f"중복 청크 ID가 발견되었습니다: {duplicates[:10]}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="B파트 RAG 적재 파이프라인 실행")
    parser.add_argument("--statutes", type=Path, default=DEFAULT_STATUTE_PATH)
    parser.add_argument("--precedents", type=Path, default=DEFAULT_PRECEDENT_PATH)
    parser.add_argument("--chunk-output", type=Path, default=DEFAULT_CHUNK_OUTPUT)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--openai-api-key", default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pipeline = BPartRAGPipeline(
        statute_path=args.statutes,
        precedent_path=args.precedents,
        chunk_output_path=args.chunk_output,
        summary_output_path=args.summary_output,
        database_url=args.database_url,
        openai_api_key=args.openai_api_key,
        dry_run=args.dry_run,
    )
    summary = pipeline.run()
    logger.info("요약: %s", json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
