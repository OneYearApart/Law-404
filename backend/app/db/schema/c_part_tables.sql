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

CREATE INDEX IF NOT EXISTS legal_documents_c_embedding_idx 
ON legal_documents_c USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE INDEX IF NOT EXISTS legal_documents_c_category_idx 
ON legal_documents_c (category_tag);

CREATE INDEX IF NOT EXISTS legal_documents_c_source_idx 
ON legal_documents_c (source_type, case_number);