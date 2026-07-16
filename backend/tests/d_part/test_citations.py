"""
build_citation_cards 테스트 (DB/네트워크 없는 순수 로직).
정렬(법령원문→판례→기타), label/content(verbatim)/is_excerpt, 빈 입력, META 직렬화.
"""
import json

from app.api.events import EventType, StreamEvent
from app.graph.parts.d_part.nodes._context import build_citation_cards
from app.rag.retrievers.base import Chunk


def _statute() -> Chunk:
    return Chunk(
        id=1, source_type="법령원문", statute_name="주택임대차보호법",
        article_no="3", content="① 임대차는 그 등기가 없는 경우에도 …",
        metadata={"조문제목": "대항력 등"},
    )


def _precedent() -> Chunk:
    return Chunk(
        id=2, source_type="판례", case_no="2023다202228",
        content="판결요지 …", source_date="2023-01-01",
        metadata={"법원명": "대법원"},
    )


def _guide_excerpt() -> Chunk:
    return Chunk(
        id=3, source_type="생활법령", content="발췌 본문 …",
        metadata={"chunk_seq": 2},         # 서브청크 → is_excerpt
    )


def test_orders_statute_then_precedent_then_other():
    cards = build_citation_cards([_guide_excerpt(), _precedent(), _statute()])
    assert [c["source_type"] for c in cards] == ["법령원문", "판례", "생활법령"]


def test_card_fields_present_and_content_verbatim():
    card = build_citation_cards([_statute()])[0]
    assert card["source_type"] == "법령원문"
    assert card["label"]                                # _source_label 결과(비어있지 않음)
    assert card["content"].startswith("① 임대차는")      # 원문 그대로(verbatim)
    assert card["is_excerpt"] is False


def test_subchunk_marked_as_excerpt():
    card = build_citation_cards([_guide_excerpt()])[0]
    assert card["is_excerpt"] is True


def test_empty_input_yields_empty_list():
    assert build_citation_cards([]) == []


def test_meta_event_is_json_serializable():
    """라우트가 내보내는 META{citations} payload가 StreamEvent로 직렬화되는지."""
    cards = build_citation_cards([_statute(), _precedent()])
    event = StreamEvent(type=EventType.META, data={"citations": cards})
    parsed = json.loads(event.model_dump_json())
    assert parsed["type"] == "meta"
    assert len(parsed["data"]["citations"]) == 2
