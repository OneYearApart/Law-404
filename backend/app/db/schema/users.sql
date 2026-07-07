-- 자체(로컬) 회원가입 전용 users 테이블
-- 소셜 로그인 없음. 수집 항목은 아이디/비밀번호/닉네임 세 가지로 최소화.

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,   -- 로그인용 아이디, 중복 방지 기준
    password_hash TEXT NOT NULL,
    nickname VARCHAR(50) UNIQUE NOT NULL,   -- 중복 불허 확정
    created_at TIMESTAMP DEFAULT now()
);
