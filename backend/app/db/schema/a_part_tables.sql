-- A파트 pgvector 테이블
-- MVP 단계에서는 독립적으로 설계/운영, 통합 단계에서 병합 논의

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS a_part_embeddings (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR(50),     -- 예: 법령조문 | 판례 | 사례집 | HUG규정
    content TEXT NOT NULL,
    metadata JSONB,                -- 법령명/조번호/사건번호/케이스번호 등
    embedding VECTOR(1536)         -- GPT 임베딩 모델 차원에 맞춰 조정
);
