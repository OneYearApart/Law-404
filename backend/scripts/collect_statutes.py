# -*- coding: utf-8 -*-
"""
D파트 근거법 조문 원문 수집 스크립트 (작업단위 1)
========================================
"원문 -> 해설 -> 상황적용" 3단 구조에서 비어있던 "원문" 레이어를 채우기 위해
law.go.kr Open API(target=law)로 근거법 조문 전문을 수집한다.

대상:
- 주택임대차보호법 (전문)
- 공인중개사법 (전문)
- 신탁법 (전문)
- 채무자회생법 (관련조문 발췌 — 상계금지/부인권/환취권 키워드로 필터링)
- 주택임대차보호법 시행령 (전문 — 최우선변제액/소액임차인 범위가 법률 본문이 아닌 여기에 있음)
- 전세사기피해자법 시행령 (전문 — 국세/지방세 안분 절차)
- 공인중개사법 시행령 (관련조문 발췌 — 확인·설명의무/손해배상/거래질서교란 키워드로 필터링)

신탁법 시행령은 조문 17개가 전부 서식·절차(수익증권 기재사항, 사채 총액 한도 등)라
신탁사기 도메인과 접점이 없어 수집 대상에서 제외한다.

작업단위 39(일반 민사 절차)로 아래 3개 법령을 추가한다. C파트(계약 후)와 주제가 겹치나,
종합문서 §13 방침대로 지금은 D파트 테이블에 독립 적재하고 통합 단계에서 조율한다:
- 민사소송법 (독촉절차 발췌 — 지급명령/독촉 키워드)
- 민사집행법 (강제경매·배당절차 발췌 — 배당/강제경매/우선변제 키워드, 전문은 노이즈 과다)
- 소액사건심판법 (전문 — 25개 조문으로 작음)

- 검색: lawSearch.do (target=law) → 법령일련번호(MST) 확인
- 상세: lawService.do (target=law) → 조문단위(조/항/호) 전문 조회
- 결과: {out}/{법령명}.json (조 단위, 항이 많으면 항 단위로도 분리된 구조)

사용법:
    python collect_statutes.py --oc Whitecube1 --out ./statutes

주의:
- collect_precedents.py와 동일하게 User-Agent는 반드시 Mozilla/5.0 계열로 설정
  (기본 UA는 WAF에 막혀 빈 응답/에러 반환됨)
"""

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_SEARCH_URL = "http://www.law.go.kr/DRF/lawSearch.do"
BASE_SERVICE_URL = "http://www.law.go.kr/DRF/lawService.do"

REQUEST_DELAY_SEC = 0.6
MAX_RETRIES = 3
RETRY_BACKOFF_SEC = 2.0

# 채무자회생법은 임대인 파산 시나리오와 직결되는 조문만 발췌 (전문이 방대함).
# 공인중개사법 시행령은 56개 조문 중 대부분이 자격시험/심의위원회/협회 등 행정사항이라
# 중개사고 관련 조문만 발췌 (56 -> 15개).
# 조문제목/조문내용/항내용에 아래 키워드 중 하나라도 포함되면 채택.
EXCERPT_KEYWORDS = {
    "채무자 회생 및 파산에 관한 법률": ["상계", "부인", "환취"],
    "공인중개사법 시행령": [
        "중개대상물",
        "확인ㆍ설명",
        "손해배상",
        "거래계약서",
        "계약금등",
        "보증보험금",
        "보증의 변경",
        "교란행위",
        "중개보수",
        "중개계약",
    ],
    # 작업단위 39: 전세보증금 반환 관련 절차 조문만 발췌 (전문은 노이즈 과다)
    "민사소송법": ["지급명령", "독촉"],
    "민사집행법": ["배당", "강제경매", "우선변제"],
}

# 수집 대상 법령 (검색 쿼리 = 정식 법령명)
TARGET_LAWS = [
    "주택임대차보호법",
    "공인중개사법",
    "신탁법",
    "채무자 회생 및 파산에 관한 법률",
    "주택임대차보호법 시행령",
    "전세사기피해자 지원 및 주거안정에 관한 특별법 시행령",
    "공인중개사법 시행령",
    "민사소송법",  # 작업단위 39 (독촉절차 발췌)
    "민사집행법",  # 작업단위 39 (강제경매·배당 발췌)
    "소액사건심판법",  # 작업단위 39 (전문)
]


def build_url(base: str, params: dict) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    return f"{base}?{urlencode(clean)}"


def fetch_xml(url: str) -> ET.Element:
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (jeonse-statute-collector/1.0)"},
            )
            with urlopen(req, timeout=15) as resp:
                raw = resp.read()

            try:
                root = ET.fromstring(raw)
            except ET.ParseError:
                preview = raw[:500].decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"XML 파싱 실패 — API가 XML이 아닌 응답을 반환함.\n"
                    f"URL: {url}\n응답 미리보기:\n{preview}"
                )

            err_msg = root.findtext(".//msg") or root.findtext(".//resultMsg")
            result_code = root.findtext(".//resultCode")
            if root.tag == "Response" and root.findtext("result"):
                raw_preview = raw[:500].decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"API 인증/권한 오류 — OC 값 또는 IP 등록 상태를 확인할 것.\n"
                    f"메시지: {root.findtext('result')} / {root.findtext('msg')}\n"
                    f"URL: {url}"
                )
            if result_code and result_code != "00":
                raise RuntimeError(
                    f"API 오류(resultCode={result_code}): {err_msg}\nURL: {url}"
                )

            return root
        except (URLError, HTTPError) as e:
            last_err = e
            print(f"  [재시도 {attempt}/{MAX_RETRIES}] 요청 실패: {e}", file=sys.stderr)
            time.sleep(RETRY_BACKOFF_SEC * attempt)
        except RuntimeError:
            raise
    raise RuntimeError(f"요청 최종 실패: {url}\n원인: {last_err}")


def search_law_mst(oc: str, law_name: str) -> dict:
    """법령명으로 검색해서 정확히 일치하는 법령의 법령일련번호(MST) 등 메타를 반환"""
    params = {"OC": oc, "target": "law", "type": "XML", "query": law_name}
    url = build_url(BASE_SEARCH_URL, params)
    root = fetch_xml(url)

    for law_el in root.findall("law"):
        name = (law_el.findtext("법령명한글") or "").strip()
        if name == law_name:
            return {
                "법령일련번호": law_el.findtext("법령일련번호"),
                "법령ID": law_el.findtext("법령ID"),
                "법령명": name,
                "공포일자": law_el.findtext("공포일자"),
                "시행일자": law_el.findtext("시행일자"),
                "소관부처명": law_el.findtext("소관부처명"),
            }
    raise RuntimeError(
        f"'{law_name}' 정확히 일치하는 법령을 검색 결과에서 찾지 못함 (검색 URL: {url})"
    )


def parse_hang_ho(hang_el: ET.Element) -> dict:
    ho_list = []
    for ho_el in hang_el.findall("호"):
        ho_list.append(
            {
                "호번호": (ho_el.findtext("호번호") or "").strip(),
                "호내용": (ho_el.findtext("호내용") or "").strip(),
            }
        )
    return {
        "항번호": (hang_el.findtext("항번호") or "").strip(),
        "항내용": (hang_el.findtext("항내용") or "").strip(),
        "호": ho_list,
    }


def get_law_articles(oc: str, mst: str) -> dict:
    """lawService.do(target=law)로 조문 전문 조회, 조/항/호 구조로 파싱"""
    params = {"OC": oc, "target": "law", "MST": mst, "type": "XML"}
    url = build_url(BASE_SERVICE_URL, params)
    root = fetch_xml(url)

    basic = root.find("기본정보")
    meta = {
        "법령ID": basic.findtext("법령ID") if basic is not None else None,
        "법령명": (basic.findtext("법령명_한글") or "").strip()
        if basic is not None
        else None,
        "공포일자": basic.findtext("공포일자") if basic is not None else None,
        "시행일자": basic.findtext("시행일자") if basic is not None else None,
        "소관부처": basic.findtext("소관부처") if basic is not None else None,
    }

    articles = []
    jomun_root = root.find("조문")
    if jomun_root is not None:
        for jo_el in jomun_root.findall("조문단위"):
            if (jo_el.findtext("조문여부") or "").strip() != "조문":
                continue  # 장/절 제목 등 비-조문 단위는 제외
            hang_list = [parse_hang_ho(h) for h in jo_el.findall("항")]
            articles.append(
                {
                    "조문번호": (jo_el.findtext("조문번호") or "").strip(),
                    "조문가지번호": (jo_el.findtext("조문가지번호") or "").strip(),
                    "조문제목": (jo_el.findtext("조문제목") or "").strip(),
                    "조문내용": (jo_el.findtext("조문내용") or "").strip(),
                    "항": hang_list,
                }
            )

    return {"meta": meta, "articles": articles}


def article_matches_keywords(article: dict, keywords: list[str]) -> bool:
    haystack_parts = [article.get("조문제목", ""), article.get("조문내용", "")]
    for hang in article.get("항", []):
        haystack_parts.append(hang.get("항내용", ""))
        for ho in hang.get("호", []):
            haystack_parts.append(ho.get("호내용", ""))
    haystack = " ".join(haystack_parts)
    return any(kw in haystack for kw in keywords)


def run_collection(oc: str, out_dir: Path, only: list[str] | None = None):
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = []

    targets = [l for l in TARGET_LAWS if l in only] if only else TARGET_LAWS
    if only:
        missing = [l for l in only if l not in TARGET_LAWS]
        if missing:
            raise SystemExit(f"--only에 TARGET_LAWS에 없는 법령: {missing}")
    for law_name in targets:
        print(f"\n=== {law_name} ===")
        print("  검색 중...")
        search_meta = search_law_mst(oc, law_name)
        mst = search_meta["법령일련번호"]
        print(
            f"  -> MST={mst}, 공포일자={search_meta['공포일자']}, 시행일자={search_meta['시행일자']}"
        )
        time.sleep(REQUEST_DELAY_SEC)

        print("  조문 전문 조회 중...")
        detail = get_law_articles(oc, mst)
        time.sleep(REQUEST_DELAY_SEC)

        all_articles = detail["articles"]
        is_excerpt = law_name in EXCERPT_KEYWORDS
        keywords = EXCERPT_KEYWORDS.get(law_name)

        if is_excerpt:
            articles = [
                a for a in all_articles if article_matches_keywords(a, keywords)
            ]
            print(
                f"  -> 전체 {len(all_articles)}개 조문 중 키워드({keywords}) 매칭 {len(articles)}개 발췌"
            )
        else:
            articles = all_articles
            print(f"  -> 전체 {len(articles)}개 조문 수집")

        record = {
            "법령명": detail["meta"]["법령명"] or search_meta["법령명"],
            "법령ID": detail["meta"]["법령ID"] or search_meta["법령ID"],
            "공포일자": detail["meta"]["공포일자"] or search_meta["공포일자"],
            "시행일자": detail["meta"]["시행일자"] or search_meta["시행일자"],
            "소관부처": detail["meta"]["소관부처"] or search_meta["소관부처명"],
            "발췌여부": is_excerpt,
            "발췌키워드": keywords if is_excerpt else None,
            "조문수": len(articles),
            "조문": articles,
        }

        out_path = out_dir / f"{law_name.replace(' ', '_')}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        print(f"  저장 완료: {out_path}")

        summary.append(
            {
                "법령명": record["법령명"],
                "시행일자": record["시행일자"],
                "발췌여부": is_excerpt,
                "조문수": len(articles),
                "파일": out_path.name,
            }
        )

    if not only:  # 부분(--only) 실행은 기존 index.json을 덮어쓰지 않는다
        summary_path = out_dir / "index.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"  인덱스: {summary_path}")

    print("\n=== 전체 완료 ===")
    for s in summary:
        tag = "(발췌)" if s["발췌여부"] else "(전문)"
        print(f"  {s['법령명']} {tag}: {s['조문수']}개 조문 -> {s['파일']}")


def sanity_check(oc: str):
    print("=== 인증/연결 상태 확인 (단일 쿼리 테스트) ===")
    print(f"OC={oc} 로 '주택임대차보호법' 검색 시도...")
    try:
        meta = search_law_mst(oc, "주택임대차보호법")
        print(f"성공: {meta}")
    except RuntimeError as e:
        print("실패. 아래 원인 메시지 확인:\n")
        print(str(e))
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="D파트 근거법 조문 원문 수집 (작업단위 1)"
    )
    parser.add_argument("--oc", required=True, help="law.go.kr Open API 인증 ID")
    parser.add_argument(
        "--out", default="./statutes", help="출력 디렉토리 (기본: ./statutes)"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="본 수집 없이 단일 쿼리로 인증/연결 상태만 확인하고 종료",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="쉼표로 구분한 법령명만 수집(기존 JSON/index.json 유지). 예: --only 민사소송법,민사집행법",
    )
    args = parser.parse_args()

    if args.check:
        sanity_check(args.oc)
        return

    only = [s.strip() for s in args.only.split(",")] if args.only else None
    run_collection(args.oc, Path(args.out), only=only)


if __name__ == "__main__":
    main()
