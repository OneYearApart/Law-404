-- C파트 pgvector 테이블
-- backend/db/schema/c_part_tables.sql

CREATE TABLE IF NOT EXISTS legal_documents_c (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    embedding vector(1536),
    statute_number VARCHAR(20),
    statute_branch VARCHAR(20),
    statute_title VARCHAR(255),
    case_number VARCHAR(50),
    case_name VARCHAR(255),
    case_date DATE,
    chunk_type VARCHAR(50),
    source_type VARCHAR(20) NOT NULL,
    category_tag INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ⚠️ ivfflat 인덱스는 현재 데이터 규모(16행)에서 사용하지 않습니다.
--    lists=100은 수천 행 이상을 전제한 값이라, 16행에서는 대부분의 리스트가 비어
--    기본 probes=1 검색이 빈 결과를 반환합니다(low recall).
--    16행 규모에서는 seq scan이 더 정확하고 빠릅니다.
--    데이터가 1,000행을 넘어가면 아래를 살리되 lists 값을 재산정하세요.
--    권장: lists ≈ 행수/1000 (최소 1)
-- CREATE INDEX IF NOT EXISTS legal_documents_c_embedding_idx 
-- ON legal_documents_c USING ivfflat (embedding vector_cosine_ops)
-- WITH (lists = 100);

CREATE INDEX IF NOT EXISTS legal_documents_c_category_idx 
ON legal_documents_c (category_tag);

CREATE INDEX IF NOT EXISTS legal_documents_c_source_idx 
ON legal_documents_c (source_type, case_number);