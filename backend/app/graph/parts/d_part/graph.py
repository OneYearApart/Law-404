"""
D파트 LangGraph 서브그래프.

흐름:
1. stage_router — 전/중/후 1차 판별
2. risk_trigger — 위험신호 감지 (단계 횡단, 신호 있으면 victim_check로 즉시 라우팅)
3. victim_check — 미인지형/인지형 판별 (전세사기피해자법 요건 슬롯 매핑)
4. special_cases — 특수상황 7가지 매칭
5. response_agent(공통) — 원문→해설→상황적용 조립 + 스트리밍 응답 생성

판단 단계(1~4)는 .ainvoke()로 동기 실행하고, 최종 답변 생성부터만 스트리밍합니다.
"""

graph = None  # TODO: LangGraph StateGraph 정의
