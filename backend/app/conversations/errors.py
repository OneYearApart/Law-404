"""
대화 도메인 예외.

ConversationNotFoundError는 "대화방이 없음"과 "타인 소유라 접근 불가"를 하나로 합칩니다.
둘을 구분해 노출하면(403 vs 404) 대화방의 존재 여부가 새므로(IDOR),
호출부는 항상 동일하게 404로 매핑해야 합니다.
"""


class ConversationNotFoundError(Exception):
    """conversation_id가 존재하지 않거나 요청 사용자의 소유가 아님 → 404로 매핑."""

    def __init__(self, conversation_id: int):
        self.conversation_id = conversation_id
        super().__init__(f"conversation {conversation_id} not found")
