"""
D파트 로컬 모델 최소 인터페이스.
방향이 정해지면 risk_trigger.py 또는 ocr_agent.py에서 이 함수를 호출합니다.
"""


async def predict(text: str) -> dict:
    raise NotImplementedError
