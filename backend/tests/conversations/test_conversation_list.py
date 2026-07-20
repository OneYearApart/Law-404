"""
사이드바 대화 목록의 제목 폴백 테스트 (DB 없는 순수 로직).

conversations.title은 summarizer가 채우기 전까지 NULL이라 그대로 내보내면 사이드바가
빈 제목을 그린다. 폴백 재료(첫 사용자 발화)가 messages 테이블에 있어 클라이언트가 대신
채울 수 없으므로(목록 응답에 메시지가 없다) 백엔드가 채운다.
"""
from app.conversations.repository import _TITLE_MAX_LEN, _UNTITLED, _fallback_title


def test_first_question_becomes_title():
    assert _fallback_title("보증금을 못 받고 있어요") == "보증금을 못 받고 있어요"


def test_no_messages_yet_falls_back_to_placeholder():
    """대화방만 만들고 질문 전이면 첫 발화가 없다 — 빈 제목 대신 기본 문구."""
    assert _fallback_title(None) == _UNTITLED
    assert _fallback_title("") == _UNTITLED
    assert _fallback_title("   ") == _UNTITLED


def test_long_question_is_truncated_for_one_line_display():
    title = _fallback_title("가" * 200)

    assert len(title) == _TITLE_MAX_LEN + 1   # 말줄임표 1자
    assert title.endswith("…")


def test_newlines_are_collapsed():
    """여러 줄 발화가 그대로 오면 사이드바 한 줄이 깨진다."""
    assert _fallback_title("전입신고를\n했는데\n\n괜찮나요") == "전입신고를 했는데 괜찮나요"
