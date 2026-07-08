"""
D파트 조문-판례-사례집 링크 구조 (작업단위9).

`d_reference_links` 테이블에 적재할 링크 row(dict)를 3단계로 생성한다:
- Tier 1 (참조조문_정밀): 판례.reference_articles(precedents_d._parse_reference_articles
  결과, 이미 법령명 승계 처리됨)를 "법령명 + 조번호" 키로 파싱해 법령원문 청크와 매칭.
  항 단위로 분리된 법령 청크(article_no="3-①")는 조번호 기준으로 base 매칭한다.
- Tier 2 (근거법_법령단위): Tier 1이 0건인 판례에 한해 근거법 필드로 법령 단위 링크
  (조 단위 미특정, linked_id=NULL + linked_statute_name).
- Tier 3 (주제태그_유사): 판례 topic_tags와 HUG사례집 topic_tags의 배열 overlap.
  HUG사례집은 작업단위8에서 topic_tags를 채우지 않았으므로, 이 모듈이
  TOPIC_TAG_KEYWORDS로 사례집 청크에 topic_tags를 먼저 부여한다(enrich_hug_topic_tags).

입력 rows는 d_part_embeddings에 이미 적재되어 실제 id를 가진 dict 목록을 전제한다
(적재/오케스트레이션은 작업단위19의 d_part_ingest.py 몫).
"""
import re

STATUTE_NAME_ALIASES = {
    "채무자회생법": "채무자 회생 및 파산에 관한 법률",
}

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
_HANG_SUFFIX_RE = re.compile(f"-([{_CIRCLED}])$")
_ARTICLE_KEY_RE = re.compile(r"^(.+?)\s*제(\d+)조(?:의(\d+))?")

TOPIC_TAG_KEYWORDS: dict[str, list[str]] = {
    "전-①등기부등본_위험신호": ["등기부등본", "말소기준권리"],
    "전-②전세가율_HUG보증보험": ["전세가율", "보증보험"],
    "전-③다가구_선순위보증금": ["다가구", "선순위 보증금", "선순위 임차인"],
    "전-⑤신탁사기": ["신탁사", "신탁사기", "수탁자"],
    "전-⑥공인중개사_허위고지": ["공인중개사", "허위", "기망"],
    "중-②근저당_추가설정": ["근저당"],
    "중-③임대인_세금체납": ["세금체납", "체납", "압류"],
    "트리거-임대인사망파산": ["임대인 사망", "임대인이 사망", "회생", "파산"],
    "후-①대항력_우선변제권_상실": ["대항력", "우선변제권"],
    "후-②이중계약_배당순위": ["배당금", "배당 순위", "배당순위", "이중계약"],
}


def tag_hug_case(content: str) -> list[str]:
    """HUG사례집 청크 본문에 TOPIC_TAG_KEYWORDS 키워드가 있으면 해당 태그를 부여."""
    return [tag for tag, keywords in TOPIC_TAG_KEYWORDS.items() if any(kw in content for kw in keywords)]


def enrich_hug_topic_tags(hug_rows: list[dict]) -> None:
    """HUG사례집 row의 topic_tags를 in-place로 채운다 (Tier 3 매칭 및 DB 적재용)."""
    for row in hug_rows:
        row["topic_tags"] = tag_hug_case(row["content"])


def _base_article_no(article_no: str) -> str:
    """항 분리 청크(article_no="3-①")를 조 단위 키("3")로 되돌린다."""
    return _HANG_SUFFIX_RE.sub("", article_no)


def _extract_article_key(citation: str) -> tuple[str, str] | None:
    """"법령명 제N조(의M)(...)" 형태 인용에서 (법령명, base_article_no)를 추출.

    조번호가 없는 인용(법령명 단독, 항/호만 승계된 조각 등)은 정밀 매칭 대상이 아니므로 None.
    """
    m = _ARTICLE_KEY_RE.match(citation)
    if not m:
        return None
    law_name = STATUTE_NAME_ALIASES.get(m.group(1).strip(), m.group(1).strip())
    base_no = f"{m.group(2)}-{m.group(3)}" if m.group(3) else m.group(2)
    return law_name, base_no


def _build_statute_index(statute_rows: list[dict]) -> dict[tuple[str, str], list[int]]:
    index: dict[tuple[str, str], list[int]] = {}
    for row in statute_rows:
        key = (row["statute_name"], _base_article_no(row["article_no"]))
        index.setdefault(key, []).append(row["id"])
    return index


def _tier1_links(precedent_row: dict, statute_index: dict[tuple[str, str], list[int]]) -> list[dict]:
    links = []
    seen_ids: set[int] = set()
    for citation in precedent_row.get("reference_articles") or []:
        key = _extract_article_key(citation)
        if key is None:
            continue
        for linked_id in statute_index.get(key, []):
            if linked_id in seen_ids:
                continue
            seen_ids.add(linked_id)
            links.append({
                "source_id": precedent_row["id"],
                "source_type": "판례",
                "linked_id": linked_id,
                "linked_type": "법령원문",
                "linked_statute_name": None,
                "match_basis": "참조조문_정밀",
            })
    return links


def _tier2_links(precedent_row: dict, known_statute_names: set[str]) -> list[dict]:
    근거법 = (precedent_row.get("metadata") or {}).get("근거법")
    if not 근거법:
        return []
    links = []
    for name in 근거법.split(";"):
        name = STATUTE_NAME_ALIASES.get(name.strip(), name.strip())
        if name not in known_statute_names:
            continue
        links.append({
            "source_id": precedent_row["id"],
            "source_type": "판례",
            "linked_id": None,
            "linked_type": "법령원문",
            "linked_statute_name": name,
            "match_basis": "근거법_법령단위",
        })
    return links


def _tier3_links(precedents: list[dict], hug_cases: list[dict]) -> list[dict]:
    links = []
    for prec in precedents:
        prec_tags = set(prec.get("topic_tags") or [])
        if not prec_tags:
            continue
        for hug in hug_cases:
            if prec_tags & set(hug.get("topic_tags") or []):
                links.append({
                    "source_id": prec["id"],
                    "source_type": "판례",
                    "linked_id": hug["id"],
                    "linked_type": "HUG사례집",
                    "linked_statute_name": None,
                    "match_basis": "주제태그_유사",
                })
    return links


def build_links(rows: list[dict]) -> list[dict]:
    """d_part_embeddings row(id 포함) 목록 -> d_reference_links row(dict) 목록."""
    precedents = [r for r in rows if r["source_type"] == "판례"]
    statutes = [r for r in rows if r["source_type"] == "법령원문"]
    hug_cases = [r for r in rows if r["source_type"] == "HUG사례집"]

    enrich_hug_topic_tags(hug_cases)
    statute_index = _build_statute_index(statutes)
    known_statute_names = {row["statute_name"] for row in statutes}

    links: list[dict] = []
    for prec in precedents:
        tier1 = _tier1_links(prec, statute_index)
        if tier1:
            links.extend(tier1)
        else:
            links.extend(_tier2_links(prec, known_statute_names))

    links.extend(_tier3_links(precedents, hug_cases))
    return links


if __name__ == "__main__":
    from precedents_d import load_precedent_chunks
    from statutes_d import load_statute_chunks
    from hug_docs_d import load_hug_chunks

    rows = load_precedent_chunks() + load_statute_chunks() + load_hug_chunks()
    for i, row in enumerate(rows, start=1):
        row["id"] = i

    links = build_links(rows)
    by_basis: dict[str, int] = {}
    for link in links:
        by_basis[link["match_basis"]] = by_basis.get(link["match_basis"], 0) + 1

    precedent_count = sum(1 for r in rows if r["source_type"] == "판례")
    linked_precedents = {l["source_id"] for l in links if l["source_type"] == "판례"}
    print(f"판례 {precedent_count}건 중 링크 생성된 판례: {len(linked_precedents)}건")
    print(f"총 링크 {len(links)}건")
    for basis, count in by_basis.items():
        print(f"  {basis}: {count}건")
