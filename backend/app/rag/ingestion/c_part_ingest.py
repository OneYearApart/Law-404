"""
========================================================================
법률 챗봇 카테고리 3 (보증금 반환, 경매배당) RAG 파이프라인
========================================================================
이 모듈은 "데이터 수집 → 청킹 → 임베딩 → DB 저장"의 4단계 파이프라인을 담당.
각 함수는 단 하나의 책임만 가지도록 설계했으므로, 독립적으로
테스트하고 수정할 수 있음. (Single Responsibility Principle)
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg2
from dotenv import load_dotenv
from openai import OpenAI
from psycopg2.extras import execute_values

# ========================================================================
# [1단계] 초기 설정 및 로깅
# ========================================================================

load_dotenv()

# basicConfig: 뭐가 잘못되었는지 알기 위해서는 항상 로깅을 첫 번째로 설정해야 됨
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# API 키와 DB 정보
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://edu:1234@localhost:5433/edudb")

# 데이터 경로 (개인 PC의 수집 데이터)
DATA_BASE_PATH = (
    Path(__file__).parent.parent.parent.parent / "data_collection_c" / "data"
)

# 카테고리 설정
CATEGORY_ID = 3  # 보증금 반환, 경매배당
CATEGORY_NAME = "보증금_반환_경매배당"

# ========================================================================
# [2단계] 조문(Statute) 청킹 로직
# ========================================================================


class StatuteChunker:
    """
    [역할] 조문을 의미있는 단위로 나누기
    [왜 필요한가]
    조문은 원래 구조가 이미 정해져 있습니다 (제X조 → ①②③...).
    이 구조를 그대로 청킹하면, 나중에 검색할 때 정확도가 올라감.
    """

    @staticmethod
    def chunk_statutes(statute_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        조문 데이터를 청킹합니다.
        Args: statute_data: JSON에서 읽은 조문 리스트
        Returns: 청킹된 조문 리스트 (각각 메타데이터 포함)
        """
        chunks = []

        for statute in statute_data:
            조문번호 = statute.get("조문번호", "")
            조문가지번호 = statute.get("조문가지번호")  # 없으면 본조(None)
            조문제목 = statute.get("조문제목", "")
            조문내용 = statute.get("조문내용", "")

            chunk = {
                "content": 조문내용,  # RAG 검색의 대상
                "statute_number": 조문번호,
                "statute_branch": 조문가지번호,
                "statute_title": 조문제목,
                "category_tag": CATEGORY_ID,
                "source_type": "statute",  # 나중에 "이건 조문이군" 구분하기 위해
                "created_at": datetime.now().isoformat(),
            }
            chunks.append(chunk)
            logger.info(f"✓ 조문 청크 생성: 제{조문번호}조 ({조문제목})")

        return chunks


# ========================================================================
# [3단계] 판례(Precedent) 청킹 로직
# ========================================================================


class PrecedentChunker:
    """
    [역할] 판례를 의미있는 단위로 나누기

    [왜 필요한가]
    판례는 긴 판결문입니다. 전체를 하나의 청크로 넣으면 임베딩 벡터가 너무 커지고,
    검색 정확도도 떨어집니다. 그래서 "판시사항", "판결요지", "판례내용"을
    각각 분리하면, 쿼리와 더 정확하게 매칭됩니다.

    [검색 정확도 개선]
    사용자: "보증금 우선변제 판례"
    → 판시사항에서만 검색하면, 더 관련성 높은 결과를 찾을 수 있음
    """

    @staticmethod
    def chunk_precedents(
        precedent_data: Dict[str, List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        """
        판례 데이터를 청킹합니다.

        """
        chunks = []

        # 각 질문 카테고리별로
        for question_id, cases in precedent_data.items():
            if not cases:  # 빈 리스트면 스킵
                continue

            for case in cases:
                사건명 = case.get("사건명", "")
                사건번호 = case.get("사건번호", "")
                판시사항 = case.get("판시사항", "")
                판결요지 = case.get("판결요지", "")
                판례내용 = case.get("판례내용", "")
                선고일자 = case.get("선고일자", "")

                # 청크 1: 판시사항 (가장 중요)
                if 판시사항:
                    chunk = {
                        "content": f"【판시사항】\n{판시사항}",
                        "case_name": 사건명,
                        "case_number": 사건번호,
                        "case_date": 선고일자,
                        "chunk_type": "판시사항",  # 검색 결과에서 "이건 판시사항이군" 알기 위해
                        "category_tag": CATEGORY_ID,
                        "source_type": "precedent",
                        "question_id": question_id,
                        "created_at": datetime.now().isoformat(),
                    }
                    chunks.append(chunk)

                # 청크 2: 판결요지
                if 판결요지:
                    chunk = {
                        "content": f"【판결요지】\n{판결요지}",
                        "case_name": 사건명,
                        "case_number": 사건번호,
                        "case_date": 선고일자,
                        "chunk_type": "판결요지",
                        "category_tag": CATEGORY_ID,
                        "source_type": "precedent",
                        "question_id": question_id,
                        "created_at": datetime.now().isoformat(),
                    }
                    chunks.append(chunk)

                # 청크 3: 판례내용 (사실관계)
                if 판례내용:
                    chunk = {
                        "content": f"【판례내용】\n{판례내용}",
                        "case_name": 사건명,
                        "case_number": 사건번호,
                        "case_date": 선고일자,
                        "chunk_type": "판례내용",
                        "category_tag": CATEGORY_ID,
                        "source_type": "precedent",
                        "question_id": question_id,
                        "created_at": datetime.now().isoformat(),
                    }
                    chunks.append(chunk)

                logger.info(f"✓ 판례 청크 생성: {사건명} ({사건번호}) - 3개 청크")

        return chunks


# ========================================================================
# [4단계] 임베딩 생성 로직
# ========================================================================


class EmbeddingGenerator:
    """
    [역할] 텍스트를 벡터로 변환

    [왜 필요한가]
    청킹된 텍스트만으로는 검색할 수 없습니다. 벡터(숫자 배열)로 변환해야
    PostgreSQL의 pgvector 확장에서 유사도 검색을 할 수 있습니다.

    """

    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.model = "text-embedding-3-small"
        self.dimension = 1536

        logger.info(f"✓ 임베딩 모델 초기화: {self.model}")

    def generate_embeddings(
        self, chunks: List[Dict[str, Any]], batch_size: int = 50
    ) -> List[Dict[str, Any]]:
        """
        청킹된 데이터를 임베딩합니다.
        """
        logger.info(f"임베딩 생성 시작 (총 {len(chunks)}개 청크)")

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [chunk["content"] for chunk in batch]

            try:
                response = self.client.embeddings.create(model=self.model, input=texts)

                # 임베딩 벡터를 청크에 붙이기
                for chunk, embedding_data in zip(batch, response.data):
                    chunk["embedding"] = embedding_data.embedding

                logger.info(f"✓ {i + len(batch)}/{len(chunks)} 임베딩 완료")

            except Exception as e:
                logger.error(f"❌ 임베딩 생성 실패 (배치 {i // batch_size}): {e}")
                raise

        logger.info(f"✅ 모든 임베딩 생성 완료")
        return chunks


# ========================================================================
# [5단계] 데이터베이스 저장 로직
# ========================================================================


class DatabaseIngestor:
    """
    [역할] 임베딩된 데이터를 PostgreSQL에 저장

    [테이블 구조]
    CREATE TABLE legal_documents_c (
        id SERIAL PRIMARY KEY,
        content TEXT,                    -- 원본 텍스트
        embedding vector(1536),          -- OpenAI 벡터 (1536차원)
        statute_number VARCHAR(20),      -- 조문번호 (조문인 경우)
        statute_branch VARCHAR(20),      -- 조문가지번호 (조문인 경우)
        statute_title VARCHAR(255),      -- 조문제목
        case_number VARCHAR(50),         -- 사건번호 (판례인 경우)
        case_name VARCHAR(255),          -- 사건명
        case_date DATE,                  -- 선고일자
        chunk_type VARCHAR(50),          -- "판시사항" | "판결요지" | "판례내용"
        source_type VARCHAR(20),         -- "statute" | "precedent"
        category_tag INT,                -- 카테고리 (1-4)
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    );
    """

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.conn = None
        self.cursor = None

    def connect(self):
        """DB에 연결"""
        try:
            self.conn = psycopg2.connect(self.database_url)
            self.cursor = self.conn.cursor()
            logger.info("✓ PostgreSQL 연결 성공")
        except Exception as e:
            logger.error(f"❌ DB 연결 실패: {e}")
            raise

    def disconnect(self):
        """DB 연결 종료"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("✓ PostgreSQL 연결 종료")

    def ingest(self, chunks: List[Dict[str, Any]]) -> int:
        """
        청킹된 데이터를 DB에 저장합니다.

        """
        logger.info(f"DB 저장 시작 (테이블: legal_documents_c, 총 {len(chunks)}행)")

        rows = []
        for chunk in chunks:
            row = (
                chunk["content"],
                chunk.get("embedding"),
                chunk.get("statute_number"),
                chunk.get("statute_branch"),
                chunk.get("statute_title"),
                chunk.get("case_number"),
                chunk.get("case_name"),
                chunk.get("case_date"),
                chunk.get("chunk_type"),
                chunk["source_type"],
                chunk["category_tag"],
                chunk["created_at"],
                datetime.now().isoformat(),
            )
            rows.append(row)

        sql = """
            INSERT INTO legal_documents_c 
            (content, embedding, statute_number, statute_branch, statute_title,
             case_number, case_name, case_date, chunk_type, source_type, 
             category_tag, created_at, updated_at)
            VALUES %s
        """

        try:
            execute_values(self.cursor, sql, rows, page_size=100)
            self.conn.commit()
            logger.info(f"✅ {len(chunks)}행 저장 완료")
            return len(chunks)
        except Exception as e:
            self.conn.rollback()
            logger.error(f"❌ DB 저장 실패: {e}")
            raise


# ========================================================================
# [6단계] 메인 파이프라인 오케스트레이션
# ========================================================================


class RAGPipeline:
    """
    [역할] 전체 파이프라인 조율

    [왜 필요한가]
    개별 함수들을 통합하는 역할을 합니다.
    """

    def __init__(self, category: int = 3):
        self.category = category
        self.statute_chunker = StatuteChunker()
        self.precedent_chunker = PrecedentChunker()
        self.embedding_generator = EmbeddingGenerator(OPENAI_API_KEY)
        self.db_ingestor = DatabaseIngestor(DATABASE_URL)

    def run(self):
        """
        전체 파이프라인을 실행합니다.

        단계:
        1. JSON 데이터 로드
        2. 청킹
        3. 임베딩
        4. DB 저장
        5. 검증
        """
        logger.info("=" * 70)
        logger.info(f"RAG 파이프라인 시작 (카테고리 {self.category})")
        logger.info("=" * 70)

        try:
            # [단계 1] 데이터 로드
            logger.info("\n[단계 1/5] 데이터 로드 중...")
            statutes = self._load_statutes()
            precedents = self._load_precedents()

            # [단계 2] 청킹
            logger.info("\n[단계 2/5] 데이터 청킹 중...")
            statute_chunks = self.statute_chunker.chunk_statutes(statutes)
            precedent_chunks = self.precedent_chunker.chunk_precedents(precedents)
            all_chunks = statute_chunks + precedent_chunks
            logger.info(f"✅ 총 {len(all_chunks)}개 청크 생성")

            # [단계 3] 임베딩
            logger.info("\n[단계 3/5] 임베딩 생성 중...")
            embedded_chunks = self.embedding_generator.generate_embeddings(all_chunks)

            # [단계 4] DB 저장
            logger.info("\n[단계 4/5] 데이터베이스에 저장 중...")
            self.db_ingestor.connect()
            saved_count = self.db_ingestor.ingest(embedded_chunks)
            self.db_ingestor.disconnect()

            # [단계 5] 검증
            logger.info("\n[단계 5/5] 저장된 데이터 검증 중...")
            self._verify_ingestion(saved_count)

            logger.info("\n" + "=" * 70)
            logger.info(f"✅ RAG 파이프라인 완료!")
            logger.info(f"   - 조문: {len(statute_chunks)}개")
            logger.info(f"   - 판례: {len(precedent_chunks)}개")
            logger.info(f"   - 총: {saved_count}개 저장")
            logger.info("=" * 70)

        except Exception as e:
            logger.error(f"❌ 파이프라인 실패: {e}")
            raise

    def _load_statutes(self) -> List[Dict[str, Any]]:
        """JSON에서 조문 데이터 로드"""
        statute_file = DATA_BASE_PATH / "statutes_카테고리3.json"

        if not statute_file.exists():
            raise FileNotFoundError(f"조문 파일을 찾을 수 없습니다: {statute_file}")

        with open(statute_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        logger.info(f"✓ 조문 {len(data)}건 로드 완료")
        return data

    def _load_precedents(self) -> Dict[str, List[Dict[str, Any]]]:
        """JSON에서 판례 데이터 로드"""
        precedent_file = DATA_BASE_PATH / "precedents_selected_카테고리3.json"

        if not precedent_file.exists():
            raise FileNotFoundError(f"판례 파일을 찾을 수 없습니다: {precedent_file}")

        with open(precedent_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        total_cases = sum(len(cases) for cases in data.values())
        logger.info(f"✓ 판례 {total_cases}건 로드 완료")
        return data

    def _verify_ingestion(self, expected_count: int):
        """
        저장된 데이터가 정상인지 검증합니다.

        """
        try:
            conn = psycopg2.connect(self.database_url)
            cursor = conn.cursor()

            # 저장된 행 개수 확인
            cursor.execute(
                "SELECT COUNT(*) FROM legal_documents_c WHERE category_tag = %s",
                (CATEGORY_ID,),
            )
            actual_count = cursor.fetchone()[0]

            if actual_count == expected_count:
                logger.info(f"✓ 저장된 행 개수 검증 성공: {actual_count}행")
            else:
                logger.warning(
                    f"⚠️ 행 개수 불일치: 예상 {expected_count}행, 실제 {actual_count}행"
                )

            # 임베딩 벡터 샘플 확인
            cursor.execute(
                "SELECT id, content, embedding FROM legal_documents_c WHERE category_tag = %s LIMIT 1",
                (CATEGORY_ID,),
            )
            row = cursor.fetchone()
            if row and row[2] is not None:
                logger.info(f"✓ 임베딩 벡터 샘플: {len(row[2])}차원 ✓")

            cursor.close()
            conn.close()

        except Exception as e:
            logger.error(f"⚠️ 검증 중 오류: {e}")


# ========================================================================
# [7단계] 실행
# ========================================================================

if __name__ == "__main__":
    pipeline = RAGPipeline(category=CATEGORY_ID)
    pipeline.run()
