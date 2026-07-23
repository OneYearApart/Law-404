"""
GPT-4o 호출 공통 저수준 래퍼 (재시도/에러처리/로깅).
팀 전체가 GPT-4o로 통일했으므로 이 파일은 원칙적으로 아무도 건드리지 않습니다.
"""

from typing import AsyncGenerator


async def call_llm_stream_raw(prompt: str) -> AsyncGenerator[str, None]:
    """GPT-4o 스트리밍 호출. 각 파트의 {part}.py 에서 이 함수를 사용합니다."""
    raise NotImplementedError
    yield  # pragma: no cover
