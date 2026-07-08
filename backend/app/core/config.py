"""
환경변수 로드 및 전역 설정.
DB 접속 정보, GPT-4o API 키, JWT secret 등을 여기서 관리합니다.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


class Settings(BaseSettings):
    database_url: str = "postgresql://edu:1234@localhost:5433/edudb"
    openai_api_key: str = ""
    jwt_secret: str = "CHANGE_ME"

    class Config:
        env_file = ".env"


settings = Settings()


@lru_cache
def get_engine() -> Engine:
    return create_engine(settings.database_url)