"""
공통 로컬 모델 최소 인터페이스.
conversations/summarizer.py 에서 이 함수를 호출합니다.
"""


async def summarize(messages: list[str]) -> str:
    raise NotImplementedError
