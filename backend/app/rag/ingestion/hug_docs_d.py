"""
D파트 HUG 자료 청킹 (작업단위 8).

대상:
- 2025전세피해지원사례집.pdf : 케이스(질문+답변) = 1청크. 2단 레이아웃(좌/우 칼럼)이라
  페이지를 절반으로 crop해서 칼럼별로 텍스트를 뽑은 뒤, 케이스 번호(1~22)가 순서대로
  나타난다는 전제로 상태머신 방식으로 케이스 경계를 찾는다.
- 주택도시보증공사_전세사기피해예방안내.pdf : Q&A(38개, 단일 컬럼) + 부록(용어사전/체크리스트/
  최우선변제액 기준표)을 별도 처리. 부록의 "전세사기 구조도"는 텍스트가 없는 이미지라 청크화 불가
  (알려진 한계 — 통합 단계에서 별도 이미지 처리 필요).

케이스 9~16(우선매수권/배당금/셀프낙찰)은 D파트 vs C파트 소관 미정 상태라
metadata.unresolved_ownership 플래그로 표시한다 (스키마 컬럼과 별개로 원본 플래그도 남김).

topic_tags는 이 단계에서 채우지 않는다 — 판례 tags와 같은 통제 어휘(전-/중-/후-/트리거-)로
매핑하는 작업은 작업단위9(TOPIC_TAG_KEYWORDS)의 몫이다.
"""
import re
from pathlib import Path

import pdfplumber

CASE_BOOK_PDF = Path(r"C:\Users\nowne\OneDrive\문서\Proj\AI Mini Project\datasource\2025전세피해지원사례집.pdf")
GUIDE_PDF = Path(
    r"C:\Users\nowne\OneDrive\문서\Proj\AI Mini Project\datasource"
    r"\주택도시보증공사_전세사기피해예방안내.pdf"
)

UNRESOLVED_OWNERSHIP_CASES = set(range(9, 17))

_CASE_MARKER_RE = re.compile(r"^(\d{1,2})\s+(\S.*)$")
_CASE_NOISE_RE = re.compile(
    r"^(전세피해지원 프로그램 및 전세피해 상담 사례집|주요\s*$|피해지원 상담 사례\s*$|주요 피해지원 상담 사례|\d{1,3}(?:\s+\d{1,3})?)$"
)


def _finalize_case(case_no: int, title: str, lines: list[str]) -> dict:
    content_lines = [l for l in lines if not _CASE_NOISE_RE.match(l.strip())]
    content = "\n".join(content_lines).strip()
    return {
        "source_type": "HUG사례집",
        "statute_name": None,
        "article_no": None,
        "case_no": f"사례집-{case_no}",
        "reference_articles": None,
        "topic_tags": None,
        "grade": None,
        "source_date": None,
        "unresolved_ownership": case_no in UNRESOLVED_OWNERSHIP_CASES,
        "content": f"{title}\n{content}" if content else title,
        "metadata": {"제목": title, "원본": "2025전세피해지원사례집.pdf"},
    }


def load_case_book_chunks() -> list[dict]:
    """사례집 PDF -> 케이스(질문+답변) 1청크. 2단 레이아웃을 좌/우 crop으로 분리해 처리."""
    chunks: list[dict] = []
    expected = 1
    current: dict | None = None

    with pdfplumber.open(CASE_BOOK_PDF) as pdf:
        for page in pdf.pages:
            w = page.width
            for crop in (page.crop((0, 0, w / 2, page.height)), page.crop((w / 2, 0, w, page.height))):
                text = crop.extract_text() or ""
                for line in text.split("\n"):
                    m = _CASE_MARKER_RE.match(line.strip())
                    if m and int(m.group(1)) == expected:
                        if current is not None:
                            chunks.append(_finalize_case(**current))
                        current = {"case_no": expected, "title": m.group(2).strip(), "lines": []}
                        expected += 1
                    elif current is not None:
                        current["lines"].append(line)

    if current is not None:
        chunks.append(_finalize_case(**current))
    return chunks


_GUIDE_NOISE_RE = re.compile(
    r"^(전세\(사기\)피해 예방 종합 안내|\d{1,3} \| HUG|주택도시보증공사 \| \d{1,3}|"
    r"\d+\s*\|\s*서설|\d+\.\s*서설.*|\d+\.\s*임대차계약의 개요.*|\d+\.\s*사례로 보는 전세피해 예방.*)$"
)


def _classify_guide_pages(pdf) -> list[str]:
    """페이지별 섹션 분류: front(서설/개요) -> qa(사례로 보는 전세피해 예방) ->
    glossary(붙임 2. 용어사전) -> appendix_tables(붙임 3/4)."""
    section = "front"
    sections = []
    for page in pdf.pages:
        head = (page.extract_text() or "")[:80]
        if "붙임 3." in head:
            section = "appendix_tables"
        elif "붙임 2. 용어사전" in head:
            section = "glossary"
        elif "사례로 보는 전세피해 예방" in head and section == "front":
            section = "qa"
        sections.append(section)
    return sections


_QA_MARKER_RE = re.compile(r"^Q(\d+)(?:-(\d+))?\s+(\S.*)$")


def _load_qa_chunks(qa_text: str) -> list[dict]:
    lines = [l for l in qa_text.split("\n") if not _GUIDE_NOISE_RE.match(l.strip())]
    text = "\n".join(lines)

    matches = list(re.finditer(r"(?m)^Q(\d+)(?:-(\d+))?\s+\S.*$", text))
    chunks = []
    for i, m in enumerate(matches):
        no, sub = m.group(1), m.group(2)
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[m.start():end].strip()
        if not block:
            continue
        q_no = f"{no}-{sub}" if sub else no
        chunks.append({
            "source_type": "HUG규정",
            "statute_name": None,
            "article_no": None,
            "case_no": f"안내-Q{q_no}",
            "reference_articles": None,
            "topic_tags": None,
            "grade": None,
            "source_date": None,
            "unresolved_ownership": False,
            "content": block,
            "metadata": {"항목유형": "QA", "원본": "주택도시보증공사_전세사기피해예방안내.pdf"},
        })
    return chunks


def _is_glossary_term(text: str) -> bool:
    """용어 표제어(공백 없는 짧은 명사)와 정의/예문(공백 포함 문장)을 구분.

    정의/예문 문장이 마침표로 끝나지 않는 경우(명사형 종결 등)가 있어 마침표 유무만으로는
    구분이 안 된다 — 표제어는 항상 공백이 없는 반면 정의/예문은 항상 공백을 포함하므로
    공백 유무를 1차 기준으로, 마침표 없음을 2차 기준(AND)으로 사용한다.
    """
    return " " not in text and "\n" not in text and not text.endswith(".")


def _load_glossary_chunks(glossary_text: str) -> list[dict]:
    quoted = list(re.finditer(r"“([^”]+)”", glossary_text))
    chunks = []
    i = 0
    while i < len(quoted):
        term = quoted[i].group(1).strip()
        if not _is_glossary_term(term):
            i += 1
            continue  # 자음 헤더(ㄱ,ㄴ..) 등 잡음 뒤에 이어지는 조각 방지
        i += 1
        rest = []
        while i < len(quoted) and not _is_glossary_term(quoted[i].group(1).strip()):
            rest.append(quoted[i].group(1).strip())
            i += 1
        definition = rest[0] if rest else None
        example = rest[1] if len(rest) > 1 else None
        content = term if not definition else f"{term}: {definition}"
        if example:
            content += f"\n예: {example}"
        chunks.append({
            "source_type": "HUG규정",
            "statute_name": None,
            "article_no": None,
            "case_no": f"안내-용어-{term}",
            "reference_articles": None,
            "topic_tags": None,
            "grade": None,
            "source_date": None,
            "unresolved_ownership": False,
            "content": content,
            "metadata": {"항목유형": "용어사전", "원본": "주택도시보증공사_전세사기피해예방안내.pdf"},
        })
    return chunks


def _load_appendix_table_chunks(pdf, page_indices: list[int]) -> list[dict]:
    chunks = []
    for idx in page_indices:
        page = pdf.pages[idx]
        tables = page.extract_tables()
        if tables:
            for ti, table in enumerate(tables):
                rows = [" | ".join(cell or "" for cell in row) for row in table]
                content = "\n".join(r for r in rows if r.strip())
                if not content:
                    continue
                chunks.append({
                    "source_type": "HUG규정",
                    "statute_name": None,
                    "article_no": None,
                    "case_no": f"안내-표-{idx}-{ti}",
                    "reference_articles": None,
                    "topic_tags": None,
                    "grade": None,
                    "source_date": None,
                    "unresolved_ownership": False,
                    "content": content,
                    "metadata": {"항목유형": "부록표", "extraction_mode": "table", "페이지": idx},
                })
        else:
            text = (page.extract_text() or "").strip()
            if text:
                chunks.append({
                    "source_type": "HUG규정",
                    "statute_name": None,
                    "article_no": None,
                    "case_no": f"안내-부록-{idx}",
                    "reference_articles": None,
                    "topic_tags": None,
                    "grade": None,
                    "source_date": None,
                    "unresolved_ownership": False,
                    "content": text,
                    "metadata": {"항목유형": "부록", "extraction_mode": "text_fallback", "페이지": idx},
                })
    return chunks


def load_guide_chunks() -> list[dict]:
    """종합안내 PDF -> Q&A 38건 + 용어사전 + 체크리스트/최우선변제액 표(부록)."""
    with pdfplumber.open(GUIDE_PDF) as pdf:
        sections = _classify_guide_pages(pdf)

        qa_text = "\n".join(pdf.pages[i].extract_text() or "" for i, s in enumerate(sections) if s == "qa")
        glossary_text = "\n".join(pdf.pages[i].extract_text() or "" for i, s in enumerate(sections) if s == "glossary")
        appendix_pages = [i for i, s in enumerate(sections) if s == "appendix_tables"]

        chunks = _load_qa_chunks(qa_text)
        chunks += _load_glossary_chunks(glossary_text)
        chunks += _load_appendix_table_chunks(pdf, appendix_pages)
    return chunks


def load_hug_chunks() -> list[dict]:
    return load_case_book_chunks() + load_guide_chunks()


if __name__ == "__main__":
    chunks = load_hug_chunks()
    case_book = [c for c in chunks if c["source_type"] == "HUG사례집"]
    guide = [c for c in chunks if c["source_type"] == "HUG규정"]
    print(f"HUG 청크 총 {len(chunks)}건")
    print(f"  사례집: {len(case_book)}건 (unresolved_ownership={sum(1 for c in case_book if c['unresolved_ownership'])}건)")
    qa = [c for c in guide if c["metadata"].get("항목유형") == "QA"]
    glossary = [c for c in guide if c["metadata"].get("항목유형") == "용어사전"]
    appendix = [c for c in guide if c["metadata"].get("항목유형") in ("부록표", "부록")]
    print(f"  안내 Q&A: {len(qa)}건, 용어사전: {len(glossary)}건, 부록: {len(appendix)}건")
