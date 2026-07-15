"""D파트 정부·공공 발간자료 청킹 (작업단위 37).

대상 (datasource/ 에 보유 중이나 기존 인제스천 대상이 아니었던 자료):
- 깡통전세(전세사기)유형및피해예방(2023).pdf : 사기 "유형"(1~6, 각 유형+사례들)과
  "피해 예방법"(계약 전/후 할일)의 2부 구조. 유형 단위로 1청크, 예방법은 계약 전/후 2청크.
- 250627(조간)(별첨) 전세사기 피해 실태조사 결과 보고서.pdf : 국토부 국회 현안보고.
  로마자 대섹션(Ⅰ~Ⅵ) + 그 아래 숫자 하위섹션 단위로 청킹.

source_type은 "정부자료"로 신설(HUG규정=보증공사 규정과 성격이 다른 국토부/정부 발간자료라
쿼터·필터에서 구분 가능하게). topic_tags는 이 단계에서 채우지 않고 HUG사례집과 동일하게
d_part_ingest가 links_d.enrich_hug_topic_tags(통제 어휘 TOPIC_TAG_KEYWORDS)로 부여한다.

같은 트리의 국회 국토교통위 보고 요약본(250627(조간) ... 국회 국토교통위 보고 ...pdf)은
위 실태조사 보고서의 보도자료 요약본(2p, 1p는 담당자 연락처)이라 중복으로 판단해 적재 제외.
"""
import re
from pathlib import Path

import pdfplumber

_BASE = Path(r"C:\Users\nowne\OneDrive\문서\Proj\AI Mini Project\datasource")
KKANGTONG_PDF = _BASE / "깡통전세(전세사기)유형및피해예방(2023).pdf"
SURVEY_PDF = _BASE / "250627(조간)(별첨) 전세사기 피해 실태조사 결과 보고서.pdf"

_SOURCE_TYPE = "정부자료"


def _base_chunk(case_no: str, content: str, metadata: dict) -> dict:
    return {
        "source_type": _SOURCE_TYPE,
        "statute_name": None,
        "article_no": None,
        "case_no": case_no,
        "reference_articles": None,
        "topic_tags": None,  # d_part_ingest가 enrich_hug_topic_tags로 채움
        "grade": None,
        "source_date": None,
        "unresolved_ownership": False,
        "content": content,
        "metadata": metadata,
    }


def _extract_lines(pdf_path: Path) -> list[str]:
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    return text.split("\n")


# ---------- 깡통전세 유형/예방 ----------

_HEADER_RE = re.compile(r"^깡통전세.*(피해 유형|피해 예방법)")
_TYPE_RE = re.compile(r"^\(유형(\d+)\)\s*(.*)$")
# "계약 전" 할일 / "계약 후" 할일 (곡선 따옴표 “ ” 또는 직선 " 모두 허용)
_PREVENT_RE = re.compile(r'^[“"]?계약\s*(전|후)[”"]?\s*할일')


def _flush(chunks: list[dict], cur: dict | None) -> None:
    if cur is None:
        return
    if len([l for l in cur["lines"] if l.strip()]) <= 1:
        return  # 헤더 한 줄만 있는 조각(대섹션 표지 등) 제외
    body = "\n".join(cur["lines"]).strip()
    chunks.append(_base_chunk(cur["case_no"], body, cur["metadata"]))


def load_kkangtong_chunks() -> list[dict]:
    """깡통전세 안내문 -> 유형1~6(각 유형+사례) + 예방법(계약 전/후)."""
    chunks: list[dict] = []
    cur: dict | None = None
    for raw in _extract_lines(KKANGTONG_PDF):
        s = raw.strip()
        if not s:
            if cur is not None:
                cur["lines"].append("")
            continue
        if _HEADER_RE.match(s):
            _flush(chunks, cur)
            cur = None
            continue
        m = _TYPE_RE.match(s)
        if m:
            _flush(chunks, cur)
            cur = {
                "case_no": f"깡통전세-유형{m.group(1)}",
                "lines": [s],
                "metadata": {"원본": KKANGTONG_PDF.name, "섹션": s, "구분": "사기유형"},
            }
            continue
        p = _PREVENT_RE.match(s)
        if p:
            _flush(chunks, cur)
            label = p.group(1)
            cur = {
                "case_no": f"깡통전세-예방법-계약{label}",
                "lines": [s],
                "metadata": {"원본": KKANGTONG_PDF.name, "섹션": f"피해 예방법 - 계약 {label} 할일", "구분": "예방법"},
            }
            continue
        if cur is not None:
            cur["lines"].append(s)
    _flush(chunks, cur)
    return chunks


# ---------- 실태조사 보고서 ----------

_ROMAN_RE = re.compile(r"^([ⅠⅡⅢⅣⅤⅥ])\.\s*(.+)$")
# 하위섹션: "숫자 한글제목" — 표 행("1 서울 8,334 ...")과 구분하기 위해
# 숫자 뒤에는 한글·공백·중점(‧·)만 오고, 선택적으로 "(...)" 부기만 허용한다.
_SUBSEC_RE = re.compile(r"^(\d)\s+([가-힣][가-힣\s‧·]{1,20})\s*(\([^)]*\))?\s*$")
_FOOTER_RE = re.compile(r"^-\s*\d+\s*-$")


def load_survey_chunks() -> list[dict]:
    """실태조사 보고서 -> 로마자 대섹션 + 숫자 하위섹션 단위 청크."""
    chunks: list[dict] = []
    cur: dict | None = None
    roman_char: str | None = None
    roman_title: str | None = None
    for raw in _extract_lines(SURVEY_PDF):
        s = raw.strip()
        if not s:
            if cur is not None:
                cur["lines"].append("")
            continue
        if _FOOTER_RE.match(s):
            continue
        rm = _ROMAN_RE.match(s)
        if rm:
            _flush(chunks, cur)
            roman_char, roman_title = rm.group(1), s
            cur = {
                "case_no": f"실태조사-{roman_char}",
                "lines": [s],
                "metadata": {"원본": SURVEY_PDF.name, "섹션": roman_title},
            }
            continue
        sm = _SUBSEC_RE.match(s)
        if sm and roman_char is not None:
            _flush(chunks, cur)
            cur = {
                "case_no": f"실태조사-{roman_char}-{sm.group(1)}",
                "lines": [s],
                "metadata": {"원본": SURVEY_PDF.name, "섹션": f"{roman_title} > {s}"},
            }
            continue
        if cur is not None:
            cur["lines"].append(s)
        # 첫 로마자 섹션 이전(표지 등)은 버림
    _flush(chunks, cur)
    return chunks


def load_gov_chunks() -> list[dict]:
    return load_kkangtong_chunks() + load_survey_chunks()


if __name__ == "__main__":
    for c in load_gov_chunks():
        first = c["content"].split("\n", 1)[0]
        print(f"[{c['case_no']:>18}] {len(c['content']):5d}자 | {first[:60]}")
    print(f"총 {len(load_gov_chunks())}청크")
