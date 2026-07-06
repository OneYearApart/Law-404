"""
대화 이력 저장/조회.

save_message()는 user가 None(비로그인)이면 아무것도 하지 않습니다(no-op).
파트별 라우터는 저장 여부를 직접 신경 쓸 필요 없이 이 함수만 호출하면 됩니다.
"""


async def save_message(user_id: int | None, part: str, role: str, content: str):
    if user_id is None:
        return  # 비로그인 사용자는 저장하지 않음
    raise NotImplementedError


async def list_conversations(user_id: int):
    raise NotImplementedError


async def load_conversation(conversation_id: int):
    raise NotImplementedError
