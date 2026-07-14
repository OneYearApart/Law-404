"""
확인 게이트(예/아니오 질문) 응답 판별 공용 유틸.

예전에는 stage_router가 긍정/부정 키워드 튜플에 부분문자열 매칭을 걸고
victim_check가 그걸 그대로 import해 구제수단 게이트에 재사용했는데, 두 방향 모두 틀렸다:
과탐("그런데요"/"문제네요"가 "네"에 매칭)과 미탐("옙"/"ㅇㅇ"/"그렇죠"를 놓침). 특히 victim_check
쪽 오탐은 has_relief_measure=True로 이어져 실제 피해자를 지원대상에서 부당 제외시킨다.
열거로는 원리적으로 못 고치는 문제라 자연어 해석은 LLM에 넘긴다("LLM이 해석하고, 코드가
판단한다" — 판단 권한은 여전히 호출하는 노드에 있다).

확인 게이트를 새로 만드는 노드는 자체 키워드 매칭을 하지 말고 반드시 이 함수를 쓸 것.
단위 21′에서 로컬모델(EXAONE)로 백엔드를 바꿀 때도 교체 지점은 이 파일 하나다.
"""
from typing import Optional

from app.llm import d_part as llm_d_part

_ANSWER_TO_BOOL = {"yes": True, "no": False}


async def parse_confirmation(question: str, user_input: str) -> Optional[bool]:
    """확인 질문에 대한 응답을 판별한다. yes → True, no → False, unclear → None.

    unclear를 절대 True로 삼키지 않는 것이 이 함수의 핵심 안전장치다 — 부분/조건부 긍정
    ("맞긴 한데 애매해요")과 질문에 답하지 않은 발화는 전부 None으로 온다. 호출부는 None을
    "재질문" 신호로 다루고, 반복되면 각자의 재시도 상한에 걸어야 한다.
    """
    result = await llm_d_part.call_confirmation(question, user_input)
    return _ANSWER_TO_BOOL.get(result["answer"])
