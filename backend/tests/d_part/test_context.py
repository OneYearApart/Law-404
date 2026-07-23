"""
_context 헬퍼 테스트 (순수 함수, DB/네트워크 없음).

- format_chunks(단위 26): statute_name/article_no/case_no/grade/법원명 등을 컨텍스트에
  명시해 모델이 조번호·사건번호를 지어내지 않게 한다.
- build_context: 생성 경로가 공유하는 컨텍스트 조립 — 근거 + 경로별 헤더 + 사용자 발화.
"""

from datetime import date

from app.graph.parts.d_part.nodes._context import (
    _format_article_no,
    build_context,
    format_chunks,
)
from app.rag.retrievers.base import Chunk


def test_format_article_no_variants():
    assert _format_article_no("75") == "제75조"
    assert _format_article_no("30-③") == "제30조 ③항"
    assert _format_article_no("3-2-①") == "제3조의2 ①항"
    assert _format_article_no("27-2") == "제27조의2"


def test_statute_chunk_shows_name_and_article():
    chunk = Chunk(
        id=1,
        source_type="법령원문",
        statute_name="주택임대차보호법",
        article_no="3-2-①",
        content="본문",
        metadata={"조문제목": "대항력등"},
    )
    out = format_chunks([chunk])
    assert out == "[법령원문 | 주택임대차보호법 제3조의2 ①항(대항력등)]\n본문"


def test_precedent_chunk_shows_court_caseno_date_grade():
    chunk = Chunk(
        id=2,
        source_type="판례",
        case_no="2022다12345",
        grade="A",
        source_date=date(2023, 5, 11),
        content="판례 본문",
        metadata={"법원명": "대법원"},
    )
    out = format_chunks([chunk])
    assert out == "[판례 | 대법원 2022다12345 (2023-05-11) | grade A]\n판례 본문"


def test_hug_case_shows_caseno_and_title():
    chunk = Chunk(
        id=3,
        source_type="HUG사례집",
        case_no="사례집-7",
        content="사례 본문",
        metadata={"제목": "전세대출 연체 문제"},
    )
    out = format_chunks([chunk])
    assert out == "[HUG사례집 | 사례집-7 · 전세대출 연체 문제]\n사례 본문"


def test_split_subchunk_marked_as_excerpt():
    chunk = Chunk(
        id=4,
        source_type="판례",
        case_no="2007가합78659",
        content="분할된 판례 일부",
        metadata={"법원명": "서울중앙지법", "chunk_seq": 1, "chunk_total": 3},
    )
    out = format_chunks([chunk])
    assert "(발췌 일부)" in out
    assert out.startswith("[판례 | 서울중앙지법 2007가합78659] (발췌 일부)\n")


def test_missing_fields_fall_back_to_source_type_only():
    chunk = Chunk(id=5, source_type="법령원문", content="메타 없는 본문")
    out = format_chunks([chunk])
    assert out == "[법령원문]\n메타 없는 본문"


def test_multiple_chunks_separated_by_blank_line():
    chunks = [
        Chunk(id=1, source_type="HUG규정", case_no="안내-Q38", content="A"),
        Chunk(id=2, source_type="HUG규정", case_no="안내-Q39", content="B"),
    ]
    out = format_chunks(chunks)
    assert out == "[HUG규정 | 안내-Q38]\nA\n\n[HUG규정 | 안내-Q39]\nB"


# ── build_context: 생성 경로가 사용자 발화를 보게 한다 ──────────────────


def test_build_context_includes_query_and_header():
    context = build_context(
        [
            Chunk(
                id=1,
                source_type="법령원문",
                content="조문 본문",
                statute_name="전세사기피해자법",
            )
        ],
        header="항목: 등기부등본 위험 신호 해석",
        query="근저당이 3개나 잡혀 있는데 계약해도 되나요",
    )

    assert "항목: 등기부등본 위험 신호 해석" in context
    assert "근저당이 3개나 잡혀 있는데 계약해도 되나요" in context
    assert "조문 본문" in context


def test_build_context_without_query_omits_the_field():
    """발화를 안 넣는 경로(response_assembly)에 빈 '사용자 발화:' 줄이 남으면 안 된다."""
    context = build_context(
        [Chunk(id=1, source_type="법령원문", content="조문")], header="판단 결과: 높음"
    )

    assert "사용자 발화" not in context
    assert context.startswith("판단 결과: 높음")
