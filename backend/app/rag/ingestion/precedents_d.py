"""
D파트 판례 청킹 (작업단위 6).

소스: collect_precedents.py 산출물 구조 (index.csv, raw/*.json, reference/*.json)
- 이 PC(WSL 마운트 경로)에만 존재 — 리포에는 복사하지 않음 (개인 개발 환경 전제)
- Grade A(판시사항/판결요지 존재)와 Grade B(전문만 존재)를 구분해 청크 content를 채우되,
  1건 = 1청크로 유지 (작업단위6 완료기준: 233건 -> 233청크)
"""
import csv
import json
import re
from datetime import date
from pathlib import Path

DATA_DIR = Path(r"C:\Users\nowne\Downloads\ai_mini_project\data")
INDEX_CSV = DATA_DIR / "index.csv"

_ISSUE_HEADER_RE = re.compile(r"^\s*(?:\[\d+\]|[가나다라마]\.)\s*")
_LAW_NAME_RE = re.compile(r"^(?:구\s+)?(.+?법(?:률)?)\s*(?:\([^)]*\)\s*)?(제\d+.*)?$")


def _parse_reference_articles(raw: str | None) -> list[str]:
    """참조조문 원문 문자열을 개별 인용 목록으로 분해 (직전 법령명 승계).

    예: "주택임대차보호법 제3조, 제3조의2, 민법 제303조"
        -> ["주택임대차보호법 제3조", "주택임대차보호법 제3조의2", "민법 제303조"]
    이 파서는 작업단위9(링크 구조)에서도 그대로 재사용한다.
    """
    if not raw:
        return []
    text = raw.replace("<br/>", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    citations: list[str] = []
    for group in re.split(r"\s*/\s*", text):
        group = _ISSUE_HEADER_RE.sub("", group).strip()
        if not group:
            continue
        current_law = None
        for segment in group.split(","):
            segment = segment.strip()
            if not segment:
                continue
            m = _LAW_NAME_RE.match(segment)
            if m and m.group(2):
                current_law = m.group(1)
                citations.append(f"{current_law} {m.group(2)}".strip())
            elif m and not m.group(2):
                # 법령명만 있고 조번호가 없는 조각 (예: 법령명 단독 인용)
                current_law = m.group(1)
                citations.append(current_law)
            elif current_law:
                citations.append(f"{current_law} {segment}")
            else:
                citations.append(segment)
    return citations


def _parse_source_date(raw: str | None) -> date | None:
    """detail.선고일자 (YYYYMMDD 문자열)를 date로 변환."""
    if not raw or len(raw) != 8 or not raw.isdigit():
        return None
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def _split_jeonmun(jeonmun: str) -> tuple[str, str | None]:
    """Grade B 전문을 사실관계/판단으로 분리 (【이유】류 헤더 기준).

    헤더를 못 찾으면 전문 전체를 content로 두고 parse_note를 남긴다.
    """
    text = jeonmun.replace("<br/>", "\n")
    m = re.search(r"【\s*이\s*유\s*】", text)
    if not m:
        return text.strip(), "이유_헤더_미발견"
    fact = text[: m.start()].strip()
    judgment = text[m.end():].strip()
    return f"[사실관계]\n{fact}\n\n[판단]\n{judgment}", None


def _build_content(detail: dict, grade: str) -> tuple[str, str | None]:
    """판결요지 우선, 없으면 판시사항, 그마저 없으면(Grade B) 전문 분리."""
    if detail.get("판결요지"):
        return detail["판결요지"].replace("<br/>", "\n").strip(), None
    if detail.get("판시사항"):
        return detail["판시사항"].replace("<br/>", "\n").strip(), "판결요지_없음_판시사항_대체"
    jeonmun = detail.get("전문") or ""
    if not jeonmun:
        return "", "본문_없음"
    return _split_jeonmun(jeonmun)


def _load_record(판례일련번호: str, grade: str) -> dict | None:
    subdir = "raw" if grade == "A" else "reference"
    path = DATA_DIR / subdir / f"{판례일련번호}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_precedent_chunks() -> list[dict]:
    """index.csv를 순회하며 판례 233건을 1건당 1청크(dict)로 변환."""
    chunks: list[dict] = []
    with open(INDEX_CSV, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        record = _load_record(row["판례일련번호"], row["grade"])
        if record is None:
            continue
        detail = record["detail"]
        tags = [t for t in record.get("tags", []) if not t.startswith("근거법-")]
        근거법_tag = next((t.split("-", 1)[1] for t in record.get("tags", []) if t.startswith("근거법-")), None)
        근거법 = row["근거법"].strip() or 근거법_tag

        content, parse_note = _build_content(detail, record["grade"])
        if not content:
            continue

        metadata = {
            "사건명": detail.get("사건명"),
            "법원명": detail.get("법원명"),
            "근거법": 근거법,
            "판례일련번호": row["판례일련번호"],
        }
        if parse_note:
            metadata["parse_note"] = parse_note

        chunks.append({
            "source_type": "판례",
            "statute_name": None,
            "article_no": None,
            "case_no": detail.get("사건번호"),
            "reference_articles": _parse_reference_articles(detail.get("참조조문")),
            "topic_tags": tags,
            "grade": record["grade"],
            "source_date": _parse_source_date(detail.get("선고일자")),
            "unresolved_ownership": False,
            "content": content,
            "metadata": metadata,
        })

    return chunks


if __name__ == "__main__":
    result = load_precedent_chunks()
    print(f"판례 청크 {len(result)}건")
    grade_a = sum(1 for c in result if c["grade"] == "A")
    grade_b = sum(1 for c in result if c["grade"] == "B")
    print(f"  Grade A: {grade_a}, Grade B: {grade_b}")
