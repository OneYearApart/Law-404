"""
D파트 법령 조문 청킹 (작업단위 7).

대상 5개 법령:
- 주택임대차보호법 / 공인중개사법 / 신탁법 / 채무자 회생 및 파산에 관한 법률
  (law.go.kr Open API 수집 결과, JSON — collect_statutes.py 산출물)
- 전세사기피해자 지원 및 주거안정에 관한 특별법
  (JSON 버전이 없어 원문 PDF를 정규식으로 파싱)

청킹 단위: 조 단위 기본, 항이 5개 이상이면 항 단위로 추가 분리.
단, 전세사기피해자법 제3조는 요건 슬롯(victim_check.py)이 항 단위 참조를 전제하므로
항 개수와 무관하게 강제 분리한다.
"""
import json
import re
from datetime import date
from pathlib import Path

import pdfplumber

STATUTES_DIR = Path(r"C:\Users\nowne\Downloads\ai_mini_project\statutes")
JEONSE_LAW_PDF = Path(
    r"C:\Users\nowne\OneDrive\문서\Proj\AI Mini Project\datasource"
    r"\전세사기피해자 지원 및 주거안정에 관한 특별법(법률)(제21634호)(20260512).pdf"
)

HANG_SPLIT_THRESHOLD = 5
FORCED_SPLIT = {("전세사기피해자 지원 및 주거안정에 관한 특별법", "3")}

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_HANG_SPLIT_RE = re.compile(f"(?=[{_CIRCLED}])")


def _parse_시행일자(raw: str | None) -> date | None:
    if not raw or len(raw) != 8 or not raw.isdigit():
        return None
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def _hang_chunks(article_no: str, statute_name: str, 시행일자: date | None, hang_list: list[dict]) -> list[dict]:
    chunks = []
    for hang in hang_list:
        ho_texts = [ho["호내용"] for ho in hang.get("호", []) if ho.get("호내용")]
        content = hang["항내용"]
        if ho_texts:
            content += "\n" + "\n".join(ho_texts)
        chunks.append({
            "source_type": "법령원문",
            "statute_name": statute_name,
            "article_no": f"{article_no}-{hang['항번호']}",
            "case_no": None,
            "reference_articles": None,
            "topic_tags": None,
            "grade": None,
            "source_date": 시행일자,
            "unresolved_ownership": False,
            "content": content,
            "metadata": {"항목유형": "항"},
        })
    return chunks


def _load_json_statute(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        record = json.load(f)

    statute_name = record["법령명"]
    시행일자 = _parse_시행일자(record.get("시행일자"))
    chunks: list[dict] = []

    for art in record["조문"]:
        base_no = art["조문번호"]
        if art.get("조문가지번호"):
            base_no = f"{base_no}-{art['조문가지번호']}"
        hang_list = art.get("항", [])
        force_split = (statute_name, base_no) in FORCED_SPLIT

        if hang_list and (force_split or len(hang_list) >= HANG_SPLIT_THRESHOLD):
            chunks.extend(_hang_chunks(base_no, statute_name, 시행일자, hang_list))
            continue

        content = art["조문내용"]
        for hang in hang_list:
            content += "\n" + hang["항내용"]
            content += "".join(f"\n{ho['호내용']}" for ho in hang.get("호", []) if ho.get("호내용"))

        chunks.append({
            "source_type": "법령원문",
            "statute_name": statute_name,
            "article_no": base_no,
            "case_no": None,
            "reference_articles": None,
            "topic_tags": None,
            "grade": None,
            "source_date": 시행일자,
            "unresolved_ownership": False,
            "content": content,
            "metadata": {"항목유형": "조", "조문제목": art.get("조문제목"), "발췌여부": record.get("발췌여부")},
        })

    return chunks


def load_json_statute_chunks() -> list[dict]:
    chunks: list[dict] = []
    for path in sorted(STATUTES_DIR.glob("*.json")):
        if path.name == "index.json":
            continue
        chunks.extend(_load_json_statute(path))
    return chunks


_NOISE_LINE_RE = re.compile(
    r"^(법제처 \d+ 국가법령정보센터|전세사기피해자 지원 및 주거안정에 관한 특별법(?: \( 약칭: 전세사기피해자법 \))?"
    r"|\[시행 .+\] \[법률 .+\]|\S+\s*\([^)]+\)\s*\d{2,3}-\d{3,4}-\d{4}(?:,\s*\d{3,4})?|제\d+장 .+|부칙.*)$"
)
_INLINE_TAG_RE = re.compile(r"<(개정|신설|전문개정|삭제)[^>]*>")
_ARTICLE_HEADER_RE = re.compile(r"제(\d+)조(?:의(\d+))?\(([^)\n]+)\)")


def _extract_jeonse_law_text() -> str:
    with pdfplumber.open(JEONSE_LAW_PDF) as pdf:
        raw = "\n".join(p.extract_text() or "" for p in pdf.pages)

    lines = [l for l in raw.split("\n") if not _NOISE_LINE_RE.match(l.strip())]
    text = _INLINE_TAG_RE.sub("", "\n".join(lines))
    return text


def _split_into_hang(article_no: str, statute_name: str, 시행일자: date, body: str) -> list[dict]:
    parts = [p.strip() for p in _HANG_SPLIT_RE.split(body) if p.strip()]
    chunks = []
    for part in parts:
        m = re.match(f"^([{_CIRCLED}])", part)
        hang_no = m.group(1) if m else None
        chunks.append({
            "source_type": "법령원문",
            "statute_name": statute_name,
            "article_no": f"{article_no}-{hang_no}" if hang_no else article_no,
            "case_no": None,
            "reference_articles": None,
            "topic_tags": None,
            "grade": None,
            "source_date": 시행일자,
            "unresolved_ownership": False,
            "content": part,
            "metadata": {"항목유형": "항"},
        })
    return chunks


def load_jeonse_law_chunks() -> list[dict]:
    """전세사기피해자법 원문 PDF -> 조/항 단위 청크 (JSON 미제공 법령용 파서)."""
    statute_name = "전세사기피해자 지원 및 주거안정에 관한 특별법"
    시행일자 = date(2026, 5, 12)
    text = _extract_jeonse_law_text()

    matches = list(_ARTICLE_HEADER_RE.finditer(text))
    chunks: list[dict] = []
    seen_no: set[str] = set()

    for i, m in enumerate(matches):
        no, sub, title = m.group(1), m.group(2), m.group(3)
        base_no = f"{no}-{sub}" if sub else no
        if base_no in seen_no:
            continue  # 목차 재등장 또는 부칙의 조번호 재사용은 무시 (첫 등장만 채택)

        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        if not body:
            continue  # 목차 항목 (본문 없이 다음 조 제목으로 바로 이어짐)

        seen_no.add(base_no)
        force_split = (statute_name, base_no) in FORCED_SPLIT
        hang_count = len(re.findall(f"[{_CIRCLED}]", body))

        if force_split or hang_count >= HANG_SPLIT_THRESHOLD:
            chunks.extend(_split_into_hang(base_no, statute_name, 시행일자, body))
            continue

        chunks.append({
            "source_type": "법령원문",
            "statute_name": statute_name,
            "article_no": base_no,
            "case_no": None,
            "reference_articles": None,
            "topic_tags": None,
            "grade": None,
            "source_date": 시행일자,
            "unresolved_ownership": False,
            "content": body,
            "metadata": {"항목유형": "조", "조문제목": title},
        })

    return chunks


def load_statute_chunks() -> list[dict]:
    return load_json_statute_chunks() + load_jeonse_law_chunks()


if __name__ == "__main__":
    chunks = load_statute_chunks()
    print(f"법령 조문 청크 {len(chunks)}건")
    by_statute: dict[str, int] = {}
    for c in chunks:
        by_statute[c["statute_name"]] = by_statute.get(c["statute_name"], 0) + 1
    for name, count in by_statute.items():
        print(f"  {name}: {count}건")
