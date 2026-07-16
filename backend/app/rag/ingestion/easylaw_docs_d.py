"""D파트 "상황적용" 층 청킹 — 찾기쉬운 생활법령정보 (작업단위 40).

collect_easylaw.py가 수집한 '전세사기 피해자 지원'(csmSeq=1972) 책자형 콘텐츠 JSON을
읽어 페이지 단위로 청킹한다. 각 페이지는 하나의 상황/주제(피해유형·피해자인정·지원프로그램
·예방)라 페이지=1청크로 둔다(과도한 조각화 방지). 본문이 임베딩 한도를 넘으면 d_part_ingest의
_split_oversized_rows가 사후 분할한다.

source_type은 "생활법령"으로 신설(법령원문/판례/HUG/정부자료와 구분되는 상황적용 해설 층).
topic_tags는 HUG사례집·정부자료와 동일하게 d_part_ingest가 통제 어휘로 부여한다.
근거조문은 본문에 인라인(「신탁법」 제2조 등)으로 남아 원문↔해설 연결의 단서가 된다.
출처(법제처 공공누리)는 metadata에 표기한다(작업단위 26 출처 메타데이터와 정합).
"""
import json
from pathlib import Path

EASYLAW_JSON = Path(
    r"C:\Users\nowne\Downloads\ai_mini_project\easylaw\전세사기_피해자_지원.json"
)


def load_easylaw_chunks() -> list[dict]:
    if not EASYLAW_JSON.exists():
        return []
    record = json.loads(EASYLAW_JSON.read_text(encoding="utf-8"))
    출처 = record.get("출처", "")
    이용조건 = record.get("이용조건", "")

    chunks: list[dict] = []
    for p in record["페이지"]:
        chunks.append({
            "source_type": "생활법령",
            "statute_name": None,
            "article_no": None,
            "case_no": f"생활법령-{p['ccfNo']}.{p['cciNo']}.{p['cnpClsNo']}",
            "reference_articles": None,
            "topic_tags": None,
            "grade": None,
            "source_date": None,
            "unresolved_ownership": False,
            "content": p["content"],
            "metadata": {
                "원본": "easylaw 생활법령",
                "제목": p["title"],
                "url": p["url"],
                "출처": 출처,
                "이용조건": 이용조건,
            },
        })
    return chunks


if __name__ == "__main__":
    chunks = load_easylaw_chunks()
    print(f"생활법령 청크 {len(chunks)}건")
    for c in chunks:
        print(f"  {c['case_no']} | {len(c['content']):5d}자 | {c['metadata']['제목'].split('>')[-1].strip()}")
