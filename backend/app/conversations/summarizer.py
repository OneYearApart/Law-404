"""
대화 요약 생성 (사이드바에 표시할 제목).

Ollama 기반 경량 로컬 모델 도입 검토 중 (한국어 성능 양호 + 가벼운 모델).
후보 모델 미정 — local_model/models/common/ 에서 실험.
"""
from app.local_model.models.common.interface import summarize as local_summarize


async def summarize_conversation(messages: list[str]) -> str:
    return await local_summarize(messages)
