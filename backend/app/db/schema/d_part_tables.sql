-- D파트 pgvector 테이블
-- MVP 단계에서는 독립적으로 설계/운영, 통합 단계에서 병합 논의
CREATE TABLE IF NOT EXISTS d_part_embeddings (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR(20) NOT NULL,      -- 법령원문 | 판례 | HUG사례집 | HUG규정
    statute_name VARCHAR(100),             -- 법령 row: 법령명
    article_no VARCHAR(20),                -- 법령 row: 조번호 (예: "3", "3-2"(가지번호), "3-①"(항분리))
    case_no VARCHAR(50),                   -- 판례 row: 사건번호 / HUG row: 케이스번호
    reference_articles TEXT[],             -- 판례의 참조조문 파싱 결과 (예: "주택임대차보호법 제3조") — 링크 구조(작업단위9)가 사용
    topic_tags TEXT[],                     -- 판례/HUG 공통 주제태그 (법령 row는 보통 없음)
    grade CHAR(1),                         -- 'A'/'B', 판례 전용
    source_date DATE,                      -- 선고일자(판례) / 시행일자(법령) / HUG는 NULL
    unresolved_ownership BOOLEAN NOT NULL DEFAULT FALSE,  -- HUG 사례집 케이스9~16(우선매수권/배당금/셀프낙찰) 귀속 미정 플래그
    content TEXT NOT NULL,                 -- 청크 원문 텍스트
    metadata JSONB,                        -- 사건명/법원명/법령ID/근거법/항목유형/원본파일명 등 소스별 롱테일 메타데이터
    embedding VECTOR(1536),                -- text-embedding-3-small 차원
    collected_at TIMESTAMP NOT NULL DEFAULT now()
);

-- 조문-판례-사례집 크로스 레퍼런스 (작업단위9)
CREATE TABLE IF NOT EXISTS d_reference_links (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES d_part_embeddings(id) ON DELETE CASCADE,
    source_type VARCHAR(20) NOT NULL,       -- 조회 시 조인 없이 필터링하기 위한 비정규화 컬럼
    linked_id INTEGER REFERENCES d_part_embeddings(id) ON DELETE CASCADE,  -- NULL이면 법령 단위 fallback 링크(조 단위 미특정)
    linked_type VARCHAR(20) NOT NULL,       -- 법령원문 | 판례 | HUG사례집
    linked_statute_name VARCHAR(100),        -- linked_id가 NULL일 때만 사용 (법령명만으로 링크)
    match_basis VARCHAR(20) NOT NULL        -- 참조조문_정밀 | 근거법_법령단위 | 주제태그_유사
);

CREATE INDEX IF NOT EXISTS idx_d_part_embeddings_hnsw ON d_part_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_d_part_embeddings_tags ON d_part_embeddings USING GIN (topic_tags);
CREATE INDEX IF NOT EXISTS idx_d_part_embeddings_statute ON d_part_embeddings (statute_name, article_no);
CREATE INDEX IF NOT EXISTS idx_d_part_embeddings_case ON d_part_embeddings (case_no);

CREATE INDEX IF NOT EXISTS idx_d_reference_links_source ON d_reference_links (source_id);
CREATE INDEX IF NOT EXISTS idx_d_reference_links_linked ON d_reference_links (linked_id);
CREATE INDEX IF NOT EXISTS idx_d_reference_links_statute ON d_reference_links (linked_statute_name);
