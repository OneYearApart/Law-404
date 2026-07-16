"""
미인지형/인지형 판별 로직 (결합형 슬롯 채우기).

1. 사용자가 상황을 자유 서술
2. LLM이 전세사기피해자법 요건 슬롯에 매핑 (schemas.py 참고)
3. 불명확한 슬롯만 추가 질문으로 보완
4. 모든 슬롯 충족 확인 시 판단 결과 제공 (높음/있음/추가확인)
   반복 질문에도 안 채워지면 Fallback(전문가 상담 안내)
"""
from app.llm.d_part import call_victim_check
from app.graph.parts.d_part.schemas import VictimRequirementSlots


async def check_victim_status(user_input: str) -> VictimRequirementSlots:
    raise NotImplementedError
