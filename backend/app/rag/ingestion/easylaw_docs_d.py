"""D파트 "상황적용" 층 청킹 — 찾기쉬운 생활법령정보 (작업단위 40, 다중 JSON 확장 49→50).

collect_easylaw.py가 수집한 생활법령 책자(csmSeq별)·백문백답 JSON을 디렉터리에서 모두 읽어
페이지 단위로 청킹한다. 각 페이지는 하나의 상황/주제(피해유형·피해자인정·지원프로그램·예방)라
페이지=1청크로 둔다(과도한 조각화 방지). 본문이 임베딩 한도를 넘으면 d_part_ingest의
_split_oversized_rows가 사후 분할한다.

source_type은 "생활법령" 유지(작업단위 40) — 새 source_type을 만들면 enrich 목록·
search_by_topic guides·open_qa 쿼터를 전부 손봐야 해 마찰이 크다. 책자/백문백답 구분은
metadata.항목유형으로 둔다(작업단위 50). topic_tags는 HUG사례집·정부자료와 동일하게
d_part_ingest가 통제 어휘로 부여한다. 출처(법제처 공공누리)는 metadata에 표기한다(작업단위 26).
"""

import json
from pathlib import Path

EASYLAW_DIR = Path(r"C:\Users\nowne\Downloads\ai_mini_project\easylaw")

_LEAF_KEYS = ("ccfNo", "cciNo", "cnpClsNo")


def _leaf_id(page: dict) -> str:
    """책자는 ccfNo.cciNo.cnpClsNo, 백문백답 등은 id로 식별자를 만든다."""
    parts = [str(page[k]) for k in _LEAF_KEYS if k in page]
    return ".".join(parts) if parts else str(page.get("id", ""))


def load_easylaw_chunks() -> list[dict]:
    if not EASYLAW_DIR.exists():
        return []

    chunks: list[dict] = []
    for path in sorted(EASYLAW_DIR.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        출처 = record.get("출처", "")
        이용조건 = record.get("이용조건", "")
        kind = record.get("항목유형", "책자")  # 수집기가 표기(책자/백문백답)
        csm = record.get("csmSeq", "")
        for p in record["페이지"]:
            leaf = _leaf_id(p)
            case_no = f"생활법령-{csm}-{leaf}" if csm else f"생활법령-{leaf}"
            chunks.append(
                {
                    "source_type": "생활법령",
                    "statute_name": None,
                    "article_no": None,
                    "case_no": case_no,
                    "reference_articles": None,
                    "topic_tags": None,
                    "grade": None,
                    "source_date": None,
                    "unresolved_ownership": False,
                    "content": p["content"],
                    "metadata": {
                        "원본": path.name,
                        "항목유형": kind,
                        "제목": p.get("title", ""),
                        "url": p.get("url", ""),
                        "출처": 출처,
                        "이용조건": 이용조건,
                    },
                }
            )
    return chunks


if __name__ == "__main__":
    chunks = load_easylaw_chunks()
    print(f"생활법령 청크 {len(chunks)}건")
    for c in chunks:
        print(
            f"  {c['case_no']} | {c['metadata']['항목유형']} | {len(c['content']):5d}자 | {c['metadata']['제목'][:40]}"
        )
