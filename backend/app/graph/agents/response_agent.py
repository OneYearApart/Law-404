"""
최종 응답 생성 에이전트 (파트 공통).
판단 결과(dict) + 검색된 조문/판례/사례 → 프롬프트 조립 → llm/{part}.py 로 스트리밍 호출.
원문→해설→상황적용 3단 구조, 3단계 가능성 언어(높음/있음/추가확인), 면책 조항 자동 삽입을 담당합니다.
"""


async def generate_response_stream(part: str, judgement: dict, retrieved: dict):
    raise NotImplementedError
