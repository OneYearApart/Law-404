"""
위험신호 감지 노드 (단계 횡단, cross-cutting).

트리거 조건 (발화 내 위험 신호):
- 경매/공매 개시 통지
- 보증금 미반환
- 임대인 연락두절/사망/파산
- 소유권 변동 인지
- 타 세입자 피해 소식

로컬 경량 분류기 도입 후보 지점 — local_model/models/d_part/ 참고.
매 턴마다 도는 로직이라 비용/속도 개선 여지가 큼.
"""
from app.llm.d_part import call_risk_trigger
# from app.local_model.models.d_part.interface import predict as local_predict  # 실험 후 연결


async def detect_risk_signal(user_input: str) -> bool:
    raise NotImplementedError
