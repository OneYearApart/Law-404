"""
공통 로컬 모델 최소 인터페이스.
conversations/summarizer.py 에서 이 함수를 호출합니다.
"""
from app.core.config import settings
from app.local_model.models.common.model_loader import generate

PROMPT_TEMPLATE = (
    "다음은 법률 상담 대화입니다. 대화 목록 사이드바에 표시할 15자 이내의 "
    "짧은 제목을 한 줄로만 답하세요. 설명이나 따옴표 없이 제목만 출력하세요.\n\n"
    "{conversation}\n\n제목:"
)


async def summarize(messages: list[str]) -> str:
    prompt = PROMPT_TEMPLATE.format(conversation="\n".join(messages))
    title = await generate(prompt, model=settings.ollama_summary_model)
    return title.strip().strip('"')
