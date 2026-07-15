"""환경변수 로드 및 전역 설정."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    database_url: str = "postgresql://edu:1234@localhost:5433/edudb"
    openai_api_key: str
    jwt_secret: str
    jwt_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    law_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_summary_model: str = "exaone3.5:latest"
    summary_trigger_turns: int = 4

    model_config = SettingsConfigDict(
        env_file=(BACKEND_ROOT / ".env", PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()


@lru_cache
def get_engine() -> Engine:
    return create_engine(settings.database_url)
