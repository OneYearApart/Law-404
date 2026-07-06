"""
환경변수 로드 및 전역 설정.
DB 접속 정보, GPT-4o API 키, JWT secret 등을 여기서 관리합니다.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://user:password@localhost:5432/jeonse_chatbot"
    openai_api_key: str = ""
    jwt_secret: str = "CHANGE_ME"

    class Config:
        env_file = ".env"


settings = Settings()
