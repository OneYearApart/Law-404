"""A파트 채팅 API에 들어오는 사용자 문장을 안전하게 정리하고 검증한다."""

from __future__ import annotations

import re
import unicodedata

MAX_CHAT_INPUT_CHARS = 4000


class ChatInputValidationError(ValueError):
    """사용자 채팅 입력이 처리 기준을 통과하지 못했을 때 발생한다."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _strip_control_characters(value: str) -> str:
    return "".join(
        character
        for character in value
        if character in {"\n", "\t"}
        or not unicodedata.category(character).startswith("C")
    )


def _looks_meaningless(value: str) -> bool:
    compact = re.sub(r"\s+", "", value)
    if not compact:
        return True

    # 문장 부호나 이모지만 반복된 입력이다.
    if not re.search(r"[0-9A-Za-z가-힣]", compact):
        return True

    # ㅋㅋㅋㅋ, ㅇㅇㅇㅇ, !!!!!처럼 같은 글자만 과도하게 반복한 입력이다.
    if len(compact) >= 4 and len(set(compact)) == 1:
        return True

    # asdf, 1234처럼 새 상담의 질문으로 보기 어려운 짧은 토큰이다.
    if re.fullmatch(r"[A-Za-z0-9]{1,24}", compact):
        return True

    return False


def normalize_chat_input(
    value: str,
    *,
    is_follow_up: bool,
    max_chars: int = MAX_CHAT_INPUT_CHARS,
) -> str:
    if not isinstance(value, str):
        raise ChatInputValidationError(
            "INVALID_CHAT_INPUT",
            "질문은 문자열로 입력해야 합니다.",
        )

    normalized = unicodedata.normalize("NFKC", value)
    normalized = _strip_control_characters(normalized)
    normalized = "\n".join(
        " ".join(line.split()) for line in normalized.splitlines()
    ).strip()

    if not normalized:
        raise ChatInputValidationError(
            "EMPTY_CHAT_INPUT",
            "질문 내용을 입력해 주세요.",
        )
    if len(normalized) > max_chars:
        raise ChatInputValidationError(
            "CHAT_INPUT_TOO_LONG",
            f"질문은 {max_chars:,}자 이내로 입력해 주세요.",
        )

    # 후속 답변의 '네', '아니요', 금액·날짜는 정상 입력일 수 있으므로
    # 의미 없는 입력 검사는 새 상담에서만 엄격하게 적용한다.
    if not is_follow_up and _looks_meaningless(normalized):
        raise ChatInputValidationError(
            "UNCLEAR_CHAT_INPUT",
            "질문을 이해하기 어렵습니다. 현재 계약 상황과 궁금한 점을 조금 더 구체적으로 입력해 주세요.",
        )

    return normalized


def requests_document_review(value: str) -> bool:
    """첨부 문서 자체를 읽어 달라는 요청인지 보수적으로 판정한다."""

    normalized = " ".join(str(value or "").lower().split())
    document_markers = ("계약서", "등기부등본", "등기부", "등기사항증명서", "첨부 문서")
    direct_review_markers = (
        "봐줘",
        "봐 주세요",
        "검토해줘",
        "검토해 주세요",
        "분석해줘",
        "분석해 주세요",
        "읽어줘",
        "읽어 주세요",
        "확인해줘",
        "확인해 주세요",
        "첨부한",
        "업로드한",
        "올린 파일",
    )
    return any(marker in normalized for marker in document_markers) and any(
        marker in normalized for marker in direct_review_markers
    )
