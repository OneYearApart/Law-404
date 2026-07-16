-- ================================================================================
-- 【SQL 스키마 마이그레이션】 C파트 판례 메타데이터
-- 
-- 파일명: 001_alter_legal_documents_c.sql
-- 위치: backend/app/db/schema/
--
-- ================================================================================

-- ════════════════════════════════════════════════════════════════════════════════
-- 1️⃣ legal_documents_c 테이블 확장
-- ════════════════════════════════════════════════════════════════════════════════

ALTER TABLE legal_documents_c ADD COLUMN IF NOT EXISTS court_level INT DEFAULT NULL;
-- 대법원(0) vs 고등법원(1) vs 지방법원(2)
-- 공식 기준: 법원 체계

ALTER TABLE legal_documents_c ADD COLUMN IF NOT EXISTS case_year INT DEFAULT NULL;
-- 판례 연도 (예: 2024)
-- 공식 기준: 판례에서 나옴

ALTER TABLE legal_documents_c ADD COLUMN IF NOT EXISTS ruling_type VARCHAR(50) DEFAULT NULL;
-- "임차인 승소" / "임대인 승소" / "기각" 등
-- 공식 기준: 판례에서 나옴

ALTER TABLE legal_documents_c ADD COLUMN IF NOT EXISTS appeal_outcome VARCHAR(50) DEFAULT NULL;
-- "상소 없음" / "상소 기각" / "상소 인용" 등
-- 공식 기준: 판례에서 나옴

ALTER TABLE legal_documents_c ADD COLUMN IF NOT EXISTS related_procedures TEXT DEFAULT NULL;
-- JSON 형식으로 연관된 절차들 저장
-- 예: {"procedures": [{"name": "임차권등기명령", "order": 1}, ...]}

-- 【인덱스 생성】
-- 빠른 검색을 위한 인덱스

CREATE INDEX IF NOT EXISTS idx_legal_documents_c_court_level 
ON legal_documents_c (court_level);
-- 대법원 판례 우선 검색

CREATE INDEX IF NOT EXISTS idx_legal_documents_c_case_year 
ON legal_documents_c (case_year DESC);
-- 최신 판례부터 조회

CREATE INDEX IF NOT EXISTS idx_legal_documents_c_ruling_type 
ON legal_documents_c (ruling_type);
-- "임차인 승소" 판례만 필터링

-- ════════════════════════════════════════════════════════════════════════════════
-- 2️⃣ region_standards 테이블 생성 (지역별 표준 정보)
-- ════════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS region_standards (
  id SERIAL PRIMARY KEY,
  region VARCHAR(50) NOT NULL UNIQUE,  -- "서울", "부산" 등
  small_deposit_threshold INT NOT NULL,  -- 소액보증금 기준액 (국토교통부)
  lawyer_fee_rate_min INT NOT NULL DEFAULT 1,  -- 변호사 수수료율 (%)
  lawyer_fee_rate_max INT NOT NULL DEFAULT 3,  -- 변호사 수수료율 (%)
  data_source VARCHAR(100),  -- 출처: 국토교통부, 대한변호사협회
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_region_standards_region ON region_standards (region);
-- "서울"을 빠르게 찾기 위한 인덱스

-- ════════════════════════════════════════════════════════════════════════════════
-- 3️⃣ procedure_info 테이블 생성 (절차별 정보)
-- ════════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS procedure_info (
  id SERIAL PRIMARY KEY,
  procedure_name VARCHAR(100) NOT NULL UNIQUE,  -- "임차권등기명령", "소액사건" 등
  description TEXT,  -- 절차 설명
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_procedure_info_name ON procedure_info (procedure_name);

-- ════════════════════════════════════════════════════════════════════════════════
-- 4️⃣ 초기 데이터 삽입: region_standards (16개 지역)
-- ════════════════════════════════════════════════════════════════════════════════

INSERT INTO region_standards 
(region, small_deposit_threshold, lawyer_fee_rate_min, lawyer_fee_rate_max, data_source) 
VALUES
('서울', 3000000, 1, 3, '대한변호사협회'),
('부산', 2500000, 1, 3, '국토교통부'),
('대구', 2500000, 1, 3, '국토교통부'),
('인천', 2500000, 1, 3, '국토교통부'),
('광주', 2000000, 1, 3, '국토교통부'),
('대전', 2000000, 1, 3, '국토교통부'),
('울산', 2000000, 1, 3, '국토교통부'),
('경기', 2500000, 1, 3, '국토교통부'),
('강원', 1500000, 1, 3, '국토교통부'),
('충북', 1500000, 1, 3, '국토교통부'),
('충남', 1500000, 1, 3, '국토교통부'),
('전북', 1500000, 1, 3, '국토교통부'),
('전남', 1500000, 1, 3, '국토교통부'),
('경북', 2000000, 1, 3, '국토교통부'),
('경남', 2000000, 1, 3, '국토교통부'),
('제주', 1500000, 1, 3, '국토교통부')
ON CONFLICT (region) DO NOTHING;

-- ════════════════════════════════════════════════════════════════════════════════
-- 5️⃣ 초기 데이터 삽입: procedure_info (기본 절차 정보만)
-- ════════════════════════════════════════════════════════════════════════════════

INSERT INTO procedure_info 
(procedure_name, description) 
VALUES
('임차권등기명령', '법원 신청으로 보증금 보호'),
('소액사건', '3천만원 이하 금액에 대한 소송'),
('일반소송', '정식 민사소송 절차'),
('내용증명', '임대인에게 보내는 경고 문서'),
('경매 배당', '임대인의 집이 경매로 나갈 때 우선 배당')
ON CONFLICT (procedure_name) DO NOTHING;

-- ════════════════════════════════════════════════════════════════════════════════
-- 검증 (마이그레이션이 제대로 되었는지 확인)
-- ════════════════════════════════════════════════════════════════════════════════

-- 아래 3개 SELECT 문은 반드시 다음 결과를 출력해야 합니다:
-- "✓ 마이그레이션 완료" / region_count = 16 / procedure_count = 5

SELECT '✓ 마이그레이션 완료' AS status;
SELECT COUNT(*) as region_count FROM region_standards;
SELECT COUNT(*) as procedure_count FROM procedure_info;