"""
LLM 생성에 넘길 컨텍스트를 조립하는 공용 헬퍼.

생성 경로(general_scenario / special_cases / recognized_general / open_qa /
response_assembly)가 공유한다.

기존에는 `[{source_type}] {content}`로 본문만 넘겨 statute_name/article_no/case_no를
전부 버렸다 → 모델이 조문번호·사건번호를 지어낼 수밖에 없었다(환각). 출처를 함께 넘기고
prompts/response_common.md의 인용 강제 규칙과 짝지어 근거 기반 인용을 유도한다.
"""
from app.rag.retrievers.base import Chunk

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"


def _format_article_no(article_no: str) -> str:
    """저장형 조번호를 사람이 읽는 형태로 변환한다.
    "3-2-①"→"제3조의2 ①항", "30-③"→"제30조 ③항", "27-2"→"제27조의2", "75"→"제75조"."""
    parts = article_no.split("-")
    result = f"제{parts[0]}조"
    hang = ""
    for p in parts[1:]:
        if p and p[0] in _CIRCLED:
            hang = f" {p}항"
        elif p.isdigit():
            result += f"의{p}"
    return result + hang


def _source_label(chunk: Chunk) -> str:
    """청크의 출처를 source_type별로 한 줄 서술한다(본문 제외). 필드가 비면 빈 문자열."""
    md = chunk.metadata or {}
    st = chunk.source_type
    if st == "법령원문":
        parts = [chunk.statute_name or ""]
        if chunk.article_no:
            parts.append(_format_article_no(chunk.article_no))
        label = " ".join(p for p in parts if p)
        title = md.get("조문제목")
        return f"{label}({title})" if label and title else label
    if st == "판례":
        head = " ".join(p for p in [md.get("법원명") or "", chunk.case_no or ""] if p)
        date = f" ({chunk.source_date})" if chunk.source_date else ""
        grade = f" | grade {chunk.grade}" if chunk.grade else ""
        return f"{head}{date}{grade}"
    if st == "HUG사례집":
        return " · ".join(p for p in [chunk.case_no or "", md.get("제목") or ""] if p)
    # HUG규정 등: 식별자(case_no)만
    return chunk.case_no or chunk.statute_name or ""


def build_context(chunks: list[Chunk], *, header: str | None = None, query: str | None = None) -> str:
    """근거 청크(+경로별 헤더 +사용자 발화)를 LLM 컨텍스트 한 덩어리로 조립한다.

    발화를 넣는 이유: 생성 경로들이 발화를 검색 쿼리로만 쓰고 정작 생성 컨텍스트엔 안 넣고
    있었다. open_qa는 "질문과 관련된 법령이 무엇을 정하는지 설명하라"는 지시를 받으면서 정작
    질문을 못 봤고, general_scenario/special_cases는 13개 항목·4종 중 무엇인지만 알 뿐 사용자가
    그 안에서 뭘 물었는지 몰랐다. 검색은 발화에 반응하는데 생성은 못 해서, 발화에 맞는 근거를
    찾아놓고도 본문이 항목 일반론으로 흐르는 grounding 불일치가 났다.

    발화를 안 넣는 경로도 있다(response_assembly) — 판정 확정 턴의 발화는 슬롯 질문에 대한
    답("아니요 없어요")이라 질문이 아니고, 그 내용은 이미 요건 충족 현황으로 컨텍스트에 있다.
    """
    parts = [part for part in (header, f"사용자 발화: {query}" if query else None) if part]
    parts.append(format_chunks(chunks))
    return "\n\n".join(parts)


def format_chunks(chunks: list[Chunk]) -> str:
    """청크들을 `[source_type | 출처]\\n본문` 블록으로 직렬화(블록 사이 빈 줄)."""
    blocks = []
    for chunk in chunks:
        label = _source_label(chunk)
        header = f"[{chunk.source_type} | {label}]" if label else f"[{chunk.source_type}]"
        # 하나의 조문/판례가 여러 서브청크로 분할된 경우(전문 아님) — 전문으로 오인해 인용하지 않게
        if (chunk.metadata or {}).get("chunk_seq") is not None:
            header += " (발췌 일부)"
        blocks.append(f"{header}\n{chunk.content}")
    return "\n\n".join(blocks)


def build_citation_cards(chunks: list[Chunk]) -> list[dict]:
    """retrieved_chunks를 META로 내보낼 근거 카드로 결정론적 변환한다(단위 46).
    content는 DB 원문 그대로(verbatim) — LLM을 거치지 않아 조문번호·사건번호가 틀릴 수 없다(§14-19).
    노출 순서: 법령원문 → 판례 → 기타(HUG/생활법령/정부자료) — '법령·판례 먼저'를 보장.
    label은 format_chunks와 동일한 _source_label을 재사용하고, 서브청크는 is_excerpt=True로
    표기해 프론트가 전문으로 오인하지 않게 한다.
    """
    order = {"법령원문": 0, "판례": 1}
    ordered = sorted(chunks, key=lambda c: order.get(c.source_type, 2))
    return [
        {
            "source_type": c.source_type,
            "label": _source_label(c),
            "content": c.content,
            "is_excerpt": (c.metadata or {}).get("chunk_seq") is not None,
        }
        for c in ordered
    ]


def match_glossary_terms(text: str, glossary: list[dict]) -> list[dict]:
    """응답 텍스트에 실제로 등장한 용어의 풀이만 골라낸다(결정론적).

    build_citation_cards와 같은 계열이다 — LLM에게 "어려운 용어를 골라 설명하라"고 시키면
    법률 용어 정의를 지어낼 수 있으므로(§14.1 "출력을 하드코딩하는 것은 맞다"), 사전에 있는
    표제어를 코드가 문자열로 대조하고 설명은 DB 원문을 그대로 쓴다.

    긴 표제어부터 훑고 이미 채택된 용어에 포함되는 짧은 용어는 버린다 — "우선변제권"이 잡힌
    글에서 "변제"까지 따로 풀면 중복이고, 사용자가 읽은 단어와도 어긋난다.
    """
    if not text:
        return []

    matched: list[dict] = []
    for entry in sorted(glossary, key=lambda e: len(e["term"]), reverse=True):
        term = entry["term"]
        if term not in text:
            continue
        if any(term in picked["term"] for picked in matched):
            continue
        matched.append(entry)

    # 사용자가 읽는 순서(본문 등장 순)로 되돌린다 — 길이순 배열은 읽기 흐름과 무관하다.
    return sorted(matched, key=lambda e: text.index(e["term"]))
