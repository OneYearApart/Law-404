"""
match_glossary_terms 테스트 (DB/네트워크/LLM 없는 순수 로직).

용어 풀이는 LLM이 고르지 않고 코드가 사전 표제어를 문자열 대조한다 — 법률 용어 정의를
모델이 지어내면 안 되기 때문(build_citation_cards와 같은 계열).
"""
from app.graph.parts.d_part.nodes._context import match_glossary_terms


def _entry(term: str) -> dict:
    return {"term": term, "description": "쉬운 설명이에요."}


GLOSSARY = [_entry("대항력"), _entry("우선변제권"), _entry("변제"), _entry("갑구"), _entry("질권")]


def test_only_terms_present_in_text_are_returned():
    text = "전입신고를 하시면 대항력이 생깁니다. 갑구도 확인해 보세요."

    matched = match_glossary_terms(text, GLOSSARY)

    assert [m["term"] for m in matched] == ["대항력", "갑구"]


def test_longer_term_wins_over_contained_shorter_term():
    """'우선변제권'이 잡힌 글에서 '변제'까지 따로 풀면 중복이다."""
    text = "확정일자를 받아두시면 우선변제권이 인정될 수 있습니다."

    matched = match_glossary_terms(text, GLOSSARY)

    assert [m["term"] for m in matched] == ["우선변제권"]


def test_shorter_term_still_matches_when_standalone():
    """포함관계 제거가 과하게 작동해 독립적으로 등장한 짧은 용어까지 삼키면 안 된다."""
    text = "임대인이 변제 능력을 잃은 경우입니다."

    matched = match_glossary_terms(text, GLOSSARY)

    assert [m["term"] for m in matched] == ["변제"]


def test_returned_in_reading_order_not_length_order():
    text = "갑구를 보시고, 대항력과 우선변제권을 확인하세요."

    matched = match_glossary_terms(text, GLOSSARY)

    assert [m["term"] for m in matched] == ["갑구", "대항력", "우선변제권"]


def test_no_match_returns_empty():
    assert match_glossary_terms("보증금을 못 받고 있어요.", GLOSSARY) == []


def test_empty_text_returns_empty():
    assert match_glossary_terms("", GLOSSARY) == []


def test_explanation_is_db_verbatim():
    """설명 문구는 DB 원문 그대로여야 한다 — 프론트/백엔드 어디서도 재가공하지 않는다."""
    matched = match_glossary_terms("질권 설정 여부", GLOSSARY)

    assert matched[0]["description"] == "쉬운 설명이에요."
