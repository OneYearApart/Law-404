"""
환경변수 로드 및 전역 설정.
DB 접속 정보, GPT-4o API 키, JWT secret 등을 여기서 관리합니다.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent

class Settings(BaseSettings):
    database_url: str = "postgresql://edu:1234@localhost:5433/edudb"
    OPENAI_API_KEY: str
    jwt_secret: str
    jwt_expire_minutes: int = 30  # access token은 여전히 stateless라 짧게 잡아 탈취 리스크 완화, 대신 refresh token으로 로그인 유지
    refresh_token_expire_days: int = 14
    law_api_key: str | None = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_TEMPERATURE: float = 0.7
    LOG_LEVEL: str = "INFO" 
    CLOVA_OCR_URL: str = ""
    CLOVA_OCR_SECRET: str = ""

    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / ".env", PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()
