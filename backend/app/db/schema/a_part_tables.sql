CREATE TABLE IF NOT EXISTS a_part_rag_documents (
    id BIGSERIAL PRIMARY KEY,
    dataset_version TEXT NOT NULL DEFAULT 'law404-rag-v1',
    collection TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_id TEXT,
    source_type TEXT,
    title TEXT,
    text TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding VECTOR(1536) NOT NULL,
    embedding_model TEXT NOT NULL DEFAULT 'text-embedding-3-small',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (dataset_version, collection, document_id)
);

CREATE INDEX IF NOT EXISTS idx_a_part_rag_documents_dataset_version
ON a_part_rag_documents (dataset_version);

CREATE INDEX IF NOT EXISTS idx_a_part_rag_documents_collection
ON a_part_rag_documents (collection);

CREATE INDEX IF NOT EXISTS idx_a_part_rag_documents_source_type
ON a_part_rag_documents (source_type);

CREATE INDEX IF NOT EXISTS idx_a_part_rag_documents_metadata_gin
ON a_part_rag_documents USING GIN (metadata);

CREATE INDEX IF NOT EXISTS idx_a_part_rag_documents_embedding_hnsw
ON a_part_rag_documents USING hnsw (embedding vector_cosine_ops);