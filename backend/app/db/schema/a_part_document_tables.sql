-- A파트 사용자 문서 원본·추출·분석·비교 결과 저장
-- 로컬 MVP에서는 원본 바이너리까지 PostgreSQL BYTEA로 보관한다.

CREATE TABLE IF NOT EXISTS a_part_documents (
    document_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type = 'pdf'),
    document_type TEXT NOT NULL,
    page_index INTEGER NOT NULL CHECK (page_index >= 1),
    original_filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    sha256 TEXT NOT NULL CHECK (char_length(sha256) = 64),
    original_bytes BYTEA NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_a_part_documents_conversation
ON a_part_documents (conversation_id);

CREATE INDEX IF NOT EXISTS idx_a_part_documents_type
ON a_part_documents (source_type, document_type, page_index);

CREATE INDEX IF NOT EXISTS idx_a_part_documents_sha256
ON a_part_documents (sha256);

CREATE TABLE IF NOT EXISTS a_part_document_extractions (
    document_id TEXT NOT NULL REFERENCES a_part_documents(document_id) ON DELETE CASCADE,
    extraction_version TEXT NOT NULL,
    processing_status TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    page_count INTEGER NOT NULL,
    successful_page_count INTEGER NOT NULL,
    failed_page_count INTEGER NOT NULL,
    direct_text_page_count INTEGER NOT NULL,
    ocr_page_count INTEGER NOT NULL,
    text_character_count INTEGER NOT NULL,
    average_ocr_confidence DOUBLE PRECISION,
    combined_text TEXT NOT NULL DEFAULT '',
    pages JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (document_id, extraction_version)
);

CREATE INDEX IF NOT EXISTS idx_a_part_document_extractions_method
ON a_part_document_extractions (extraction_method);

CREATE TABLE IF NOT EXISTS a_part_document_analyses (
    conversation_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type = 'pdf'),
    document_type TEXT NOT NULL,
    analysis_version TEXT NOT NULL,
    source_document_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    result JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (conversation_id, source_type, document_type, analysis_version)
);

CREATE TABLE IF NOT EXISTS a_part_document_comparisons (
    conversation_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type = 'pdf'),
    analysis_version TEXT NOT NULL,
    result JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (conversation_id, source_type, analysis_version)
);

