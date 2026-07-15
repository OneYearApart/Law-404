# -*- coding: utf-8 -*-
"""
D파트 판례 자동 수집 스크립트 (Track B)
========================================
전세사기피해자법 시행(2026.5.12) 이전부터 존재하던 기존 법령(주택임대차보호법,
공인중개사법, 신탁법, 채무자회생법, 형법 등)을 근거로 하는 판례를 law.go.kr
Open API에서 수집하여, D파트 13개 항목/7개 특수상황 태그별로 분류·저장한다.

- 검색: lawSearch.do (target=prec, search=2 본문검색)
- 상세: lawService.do (target=prec) → 판시사항/판결요지/참조조문/전문
- 동일 판례가 여러 항목 쿼리에 걸리면(예: 전-③ ↔ 전-⑥ 공유 판례군) 태그를 병합하고
  원문은 1회만 저장 (재사용 구조)
- 결과: /output_dir/raw/{판례일련번호}.json (개별), index.csv (전체 요약)

사용법:
    python collect_precedents.py --oc Whitecube1 --out ./data

주의:
- law.go.kr는 사설/사내 네트워크 정책상 접근 제한이 걸린 환경에서는 호출이 실패할 수 있음
- 초당 과도한 호출은 차단될 수 있으므로 REQUEST_DELAY_SEC 유지 권장
- Track A(전세사기피해자법 자체를 참조조문으로 하는 판례)는 build_track_a_queries()에서
  별도로 확인용 1~2건만 시험 검색
"""

import argparse
import csv
import json
import threading
import time
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

BASE_SEARCH_URL = "http://www.law.go.kr/DRF/lawSearch.do"
BASE_SERVICE_URL = "http://www.law.go.kr/DRF/lawService.do"

REQUEST_DELAY_SEC = 0.6   # 호출 간 최소 대기 시간 (과도한 트래픽 방지)
MAX_RETRIES = 3
RETRY_BACKOFF_SEC = 2.0
PAGE_DISPLAY = 100        # 목록 조회 시 페이지당 건수
DEBUG = False             # --debug 플래그로 활성화, 원본 응답을 debug_raw/에 저장
DEBUG_DIR = Path("./debug_raw")

# Track C(5개 근거법 병렬 수집)에서 여러 법을 동시에 조회할 때도 law.go.kr에 대한
# 실제 호출은 이 락으로 직렬화해 REQUEST_DELAY_SEC 간격을 지킨다 (차단 방지).
_RATE_LIMIT_LOCK = threading.Lock()


def rate_limited_call(fn, *args, **kwargs):
    with _RATE_LIMIT_LOCK:
        result = fn(*args, **kwargs)
        time.sleep(REQUEST_DELAY_SEC)
        return result

# -----------------------------------------------------------------------
# 1. Track B 매핑표 — 항목 태그별 검색 쿼리 정의
#    (대화에서 확정한 표를 그대로 코드화. 필요 시 이 리스트만 수정하면 됨)
# -----------------------------------------------------------------------
TRACK_B_QUERIES = {
    "전-①등기부등본_위험신호": [
        {"query": "임차권 대항력 근저당권 선순위", "JO": None},
    ],
    "전-②전세가율_HUG보증보험": [
        {"query": "전세보증금 반환보증 면책", "JO": None},
    ],
    "전-③다가구_선순위보증금": [
        {"query": "다가구주택 선순위 임차보증금", "JO": None},
    ],
    "전-⑤신탁사기": [
        {"query": "신탁부동산 임대차 수탁자 동의", "JO": None},
    ],
    "전-⑥공인중개사_허위고지": [
        {"query": "중개대상물 확인설명의무 위반 손해배상", "JO": None},
    ],
    "중-②근저당_추가설정": [
        {"query": "임대차 존속 중 근저당권 설정 대항력", "JO": None},
    ],
    "중-③임대인_세금체납": [
        {"query": "당해세 우선 임차보증금 배당", "JO": None},
    ],
    "후-①대항력_우선변제권_상실": [
        {"query": "임차권등기명령 대항력 상실 이사", "JO": None},
    ],
    "후-②이중계약_배당순위": [
        {"query": "이중임대차 배당순위", "JO": None},
    ],
    "특수-①임대인_사망파산": [
        {"query": "임대인 파산 임차보증금 반환채권", "JO": None},
    ],
    "특수-⑤형사고소_무고죄": [
        {"query": "전세보증금 편취 사기죄", "JO": None},
        {"query": "전세보증금 편취 무고죄", "JO": None},
    ],
}

# Track A: 전세사기피해자법 자체를 참조조문으로 하는 판례 존재 여부 확인용
TRACK_A_QUERIES = [
    {"tag": "전세사기피해자법_직접판례_확인", "query": "전세사기피해자법", "JO": None},
]

# 본문검색(search=2)은 형태소 단위로 매칭되어 "전세사기피해자법" 쿼리가 "사기" 형태소만으로도
# 걸릴 수 있음(뇌물수수·선거법위반 등 무관 사건 다수 유입 확인됨). 따라서 검색 결과는 후보일 뿐이고,
# 상세 조회 후 참조조문/판시사항/판결요지에 법령명 전체 문자열이 실제로 등장하는지로 최종 필터링한다.
TRACK_A_LAW_ALIASES = ["전세사기피해자 지원 및 주거안정에 관한 특별법", "전세사기피해자법"]


def is_track_a_genuine(detail: dict) -> bool:
    haystack = " ".join(filter(None, [
        detail.get("참조조문"), detail.get("판시사항"), detail.get("판결요지"),
    ]))
    return any(alias in haystack for alias in TRACK_A_LAW_ALIASES)


# -----------------------------------------------------------------------
# Track C: 근거법 보강 병렬 수집 (2026-07 작업지시서 작업3)
# 현재 참조조문 기준 커버리지 부족한 4개 근거법(형법/공인중개사법/신탁법/채무자회생법)을
# 대상으로 임대차·전세 맥락 검색어로 수집한다. law.go.kr 본문검색은 형태소 단위로 매칭되어
# 무관 사건이 섞일 수 있으므로(Track A에서 확인된 문제), 검색 결과는 후보일 뿐이고 상세 조회 후
# 참조조문에 해당 근거법 명칭이 실제로 등장하는지로 최종 확정한다.
# -----------------------------------------------------------------------
TRACK_C_QUERIES = {
    "형법": [
        {"query": "전세보증금 편취 무자본 갭투자 사기죄"},
        {"query": "임차보증금 편취 조직적 사기범행"},
        {"query": "임대인 임차보증금 횡령 배임"},
    ],
    "공인중개사법": [
        {"query": "개업공인중개사 손해배상책임 업무보증"},
        {"query": "공인중개사 중개보수 초과수수 반환"},
        {"query": "공인중개사 자격취소 업무정지 처분"},
    ],
    "신탁법": [
        {"query": "신탁부동산 임대차 수탁자 권한 대항력"},
        {"query": "신탁 우선수익자 임대차보증금 반환"},
        {"query": "신탁재산 임차인 대항력 수익자"},
    ],
    "채무자회생법": [
        {"query": "임대인 파산 임차보증금 반환채권"},
        {"query": "임차인 회생절차 보증금"},
        {"query": "임대인 회생절차 임대차보증금"},
        {"query": "파산관재인 임대차계약 해지 보증금"},
    ],
}

TRACK_C_LAW_ALIASES = {
    "형법": ["형법"],
    "공인중개사법": ["공인중개사의 업무 및 부동산 거래신고에 관한 법률", "부동산중개업법"],
    "신탁법": ["신탁법"],
    "채무자회생법": ["채무자 회생 및 파산에 관한 법률", "채무자회생법", "회사정리법", "화의법"],
}


def is_track_c_genuine(law: str, detail: dict) -> bool:
    haystack = " ".join(filter(None, [detail.get("참조조문"), detail.get("판시사항")]))
    return any(alias in haystack for alias in TRACK_C_LAW_ALIASES[law])


def _search_law(oc: str, law: str, query_list: list[dict]) -> tuple[str, list[dict]]:
    """한 근거법에 대한 검색어 목록을 순차 조회 (호출 자체는 rate_limited_call로 직렬화됨)"""
    results = []
    for q in query_list:
        page_results = rate_limited_call(search_all_pages_serial, oc, q["query"], q.get("JO"))
        print(f"  [{law}] 검색: {q['query']} -> {len(page_results)}건")
        results.extend(page_results)
    return law, results


def search_all_pages_serial(oc: str, query: str, jo: str = None) -> list[dict]:
    """search_all_pages와 동일하지만 내부 sleep 없이 즉시 반환 (호출부에서 rate_limited_call로 간격 제어)"""
    all_results = []
    page = 1
    while True:
        results, total_cnt = search_precedents(oc, query, jo, page)
        all_results.extend(results)
        if len(all_results) >= total_cnt or not results:
            break
        page += 1
    return all_results


def run_track_c(oc: str, out_dir: Path):
    raw_dir = out_dir / "raw"
    ref_dir = out_dir / "reference"
    excluded_dir = out_dir / "excluded"
    for d in (raw_dir, ref_dir, excluded_dir):
        d.mkdir(parents=True, exist_ok=True)

    print("\n=== Track C: 근거법 보강 병렬 수집 (형법/공인중개사법/신탁법/채무자회생법) ===")

    # --- 1) 4개 법 동시 검색 (concurrent.futures) ---
    candidates: dict[str, dict] = {}  # pid -> {"laws": set(), "meta": {...}}
    with ThreadPoolExecutor(max_workers=len(TRACK_C_QUERIES)) as executor:
        futures = [
            executor.submit(_search_law, oc, law, query_list)
            for law, query_list in TRACK_C_QUERIES.items()
        ]
        for future in as_completed(futures):
            law, results = future.result()
            for r in results:
                pid = r["판례일련번호"]
                if pid not in candidates:
                    candidates[pid] = {"laws": set(), "meta": r}
                candidates[pid]["laws"].add(law)

    print(f"\n중복 제거 후 검색 후보 {len(candidates)}건. 근거법 인용 여부 확인 및 상세 조회 시작...")

    # --- 2) 상세 조회 + 근거법 인용 검증 + 등급 산정 + 저장 ---
    law_counts = {law: {"검색후보": 0, "확정": 0, "신규": 0} for law in TRACK_C_QUERIES}
    for law in TRACK_C_QUERIES:
        law_counts[law]["검색후보"] = sum(1 for c in candidates.values() if law in c["laws"])

    index_path = out_dir / "index.csv"
    existing_rows = []
    if index_path.exists():
        with open(index_path, encoding="utf-8-sig") as f:
            existing_rows = list(csv.DictReader(f))
    existing_by_pid = {r["판례일련번호"]: r for r in existing_rows}

    for i, (pid, entry) in enumerate(candidates.items(), 1):
        existing_path, existing = find_existing((raw_dir, ref_dir, excluded_dir), pid)

        if existing is not None:
            detail = existing["detail"]
        else:
            print(f"  [{i}/{len(candidates)}] 상세 조회: {pid} ({entry['meta']['사건명'][:40]})")
            try:
                detail = rate_limited_call(get_precedent_detail, oc, pid)
            except RuntimeError as e:
                print(f"    !! 상세 조회 실패, 스킵: {e}", file=sys.stderr)
                continue

        confirmed_laws = sorted(l for l in entry["laws"] if is_track_c_genuine(l, detail))
        if not confirmed_laws:
            continue  # 형태소 노이즈 — 어떤 근거법도 실제 인용되지 않음
        for l in confirmed_laws:
            law_counts[l]["확정"] += 1

        if existing is not None:
            row = existing_by_pid.get(pid)
            prev_laws = set(filter(None, (row["근거법"].split(";") if row and row.get("근거법") else [])))
            row_laws = sorted(prev_laws | set(confirmed_laws))
            if row is not None:
                row["근거법"] = ";".join(row_laws)
            else:
                existing_by_pid[pid] = {
                    "판례일련번호": pid, "사건명": existing["meta"].get("사건명"),
                    "선고일자": existing["meta"].get("선고일자"),
                    "tags": ";".join(existing.get("tags", [])),
                    "grade": existing.get("grade", "?"), "근거법": ";".join(row_laws),
                }
            continue

        grade = grade_precedent(detail)
        target_dir = {"A": raw_dir, "B": ref_dir, "C": excluded_dir}[grade]
        record = {"tags": [], "grade": grade, "meta": entry["meta"], "detail": detail,
                   "근거법": confirmed_laws}
        with open(target_dir / f"{pid}.json", "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        for l in confirmed_laws:
            law_counts[l]["신규"] += 1

        existing_by_pid[pid] = {
            "판례일련번호": pid, "사건명": entry["meta"].get("사건명"),
            "선고일자": entry["meta"].get("선고일자"), "tags": "",
            "grade": grade, "근거법": ";".join(confirmed_laws),
        }

    # --- 3) index.csv 갱신 ---
    with open(index_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["판례일련번호", "사건명", "선고일자", "tags", "grade", "근거법"])
        writer.writeheader()
        writer.writerows(existing_by_pid.values())

    print("\n=== Track C 완료 ===")
    for law, counts in law_counts.items():
        print(f"  {law}: 검색후보 {counts['검색후보']}건 -> 근거법 인용 확정 {counts['확정']}건 (신규 저장 {counts['신규']}건)")
    print(f"  인덱스: {index_path}")


# -----------------------------------------------------------------------
# 신탁법 재수집 타겟 라운드 (2026-07 작업지시서: 클로드코드_작업지시서_신탁법재수집.md)
# Track C의 "신탁법" 검색어("신탁부동산 임대차 수탁자 권한 대항력" 등)로는 3건만 확정되어
# D파트 전-⑤(임대인 실제소유자 여부/신탁사기) 항목 근거가 부족함. 실제 판례는 "신탁사기"라는
# 표현보다 명의신탁/부동산신탁의 법률관계를 다투는 민사 판례로 존재할 가능성이 높아 검색어를
# 교체한다. 참조조문에 "신탁법"이 있어도 세금·수익권 분쟁 등 임대차와 무관한 사건이 섞이므로
# (기존 index.csv의 B등급 신탁법 후보들이 이 문제를 보여줌), 판시사항/판결요지/사건명에 임대차
# 맥락 키워드가 실제로 등장하는지 2차 확인 후에만 확정한다.
# -----------------------------------------------------------------------
TRUST_LAW_RECOLLECT_QUERIES = [
    "명의신탁 임대차",
    "부동산 신탁 임대차보증금",
    "수탁자 임대인",
    "신탁 임대차 대항력",
    "신탁등기 임차보증금 반환",
]

TRUST_LAW_RECOLLECT_TAG = "전-⑤신탁사기"
TRUST_LAW_LEASE_KEYWORDS = ["임대차", "임차", "보증금", "임대인"]


def is_trust_law_lease_related(detail: dict) -> bool:
    if not is_track_c_genuine("신탁법", detail):
        return False
    haystack = " ".join(filter(None, [
        detail.get("판시사항"), detail.get("판결요지"), detail.get("사건명"),
    ]))
    return any(kw in haystack for kw in TRUST_LAW_LEASE_KEYWORDS)


def run_trust_law_recollect(oc: str, out_dir: Path):
    raw_dir = out_dir / "raw"
    ref_dir = out_dir / "reference"
    excluded_dir = out_dir / "excluded"
    for d in (raw_dir, ref_dir, excluded_dir):
        d.mkdir(parents=True, exist_ok=True)

    print("\n=== 신탁법 재수집 타겟 라운드 ===")

    index_path = out_dir / "index.csv"
    existing_rows = []
    if index_path.exists():
        with open(index_path, encoding="utf-8-sig") as f:
            existing_rows = list(csv.DictReader(f))
    existing_by_pid = {r["판례일련번호"]: r for r in existing_rows}

    # --- 1) 검색어별 후보 수집 (쿼리별 유효성 확인을 위해 출처 쿼리 기록) ---
    query_stats = {q: {"검색후보": 0, "확정": 0} for q in TRUST_LAW_RECOLLECT_QUERIES}
    candidates: dict[str, dict] = {}  # pid -> {"meta": {...}, "queries": set()}
    for query in TRUST_LAW_RECOLLECT_QUERIES:
        results = rate_limited_call(search_all_pages_serial, oc, query)
        print(f"  검색: {query} -> {len(results)}건")
        query_stats[query]["검색후보"] = len(results)
        for r in results:
            pid = r["판례일련번호"]
            if pid not in candidates:
                candidates[pid] = {"meta": r, "queries": set()}
            candidates[pid]["queries"].add(query)

    print(f"\n중복 제거 후 검색 후보 {len(candidates)}건. 기존 수집분 스킵 후 상세 조회 시작...")

    # --- 2) 상세 조회 + 임대차 맥락 검증 + 등급 산정 + 저장 (A/B만 채택) ---
    new_count = 0
    skipped_existing = 0
    for i, (pid, entry) in enumerate(candidates.items(), 1):
        existing_path, existing = find_existing((raw_dir, ref_dir, excluded_dir), pid)
        if existing is not None:
            skipped_existing += 1
            continue

        print(f"  [{i}/{len(candidates)}] 상세 조회: {pid} ({entry['meta']['사건명'][:40]})")
        try:
            detail = rate_limited_call(get_precedent_detail, oc, pid)
        except RuntimeError as e:
            print(f"    !! 상세 조회 실패, 스킵: {e}", file=sys.stderr)
            continue

        if not is_trust_law_lease_related(detail):
            continue  # 신탁법 인용은 있으나 임대차/보증금 쟁점과 무관 — 노이즈로 제외

        for q in entry["queries"]:
            query_stats[q]["확정"] += 1

        grade = grade_precedent(detail)
        if grade == "C":
            print(f"    -> C등급(요지/전문 모두 없음), 목표 등급(A/B) 미달로 제외")
            continue

        target_dir = raw_dir if grade == "A" else ref_dir
        record = {
            "tags": [TRUST_LAW_RECOLLECT_TAG], "grade": grade,
            "meta": entry["meta"], "detail": detail, "근거법": ["신탁법"],
        }
        with open(target_dir / f"{pid}.json", "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        existing_by_pid[pid] = {
            "판례일련번호": pid, "사건명": entry["meta"].get("사건명"),
            "선고일자": entry["meta"].get("선고일자"), "tags": TRUST_LAW_RECOLLECT_TAG,
            "grade": grade, "근거법": "신탁법",
        }
        new_count += 1

    # --- 3) index.csv 갱신 ---
    with open(index_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["판례일련번호", "사건명", "선고일자", "tags", "grade", "근거법"])
        writer.writeheader()
        writer.writerows(existing_by_pid.values())

    print("\n=== 신탁법 재수집 완료 ===")
    print(f"  신규 확정(A/B): {new_count}건 (기존 수집분과 중복 스킵: {skipped_existing}건)")
    print("  검색어별 유효성:")
    for query, counts in query_stats.items():
        print(f"    \"{query}\": 검색후보 {counts['검색후보']}건 -> 확정 {counts['확정']}건")
    print(f"  인덱스: {index_path}")


# -----------------------------------------------------------------------
# 중-① 소유권변동 재수집 타겟 라운드 (작업단위 42)
# 코퍼스 커버리지 매트릭스에서 유일하게 진짜 0건으로 남은 항목(중-①소유권_변동모니터링).
# 임차 중 임대인이 바뀌는 상황(주택 양도 시 양수인의 임대인 지위 승계, 주임법 제3조제4항)의
# 판례를 겨냥한다. "소유권 이전"만으론 명의신탁·소유권말소 등 임대차 무관 사건이 대거 섞이므로,
# 판시사항/판결요지/사건명에 임대차 맥락과 승계/양수 맥락이 함께 등장하는지 2차 검증한다
# (지시서 42의 "내용 기반 노이즈 필터").
# -----------------------------------------------------------------------
OWNERSHIP_RECOLLECT_QUERIES = [
    "임차주택 양수인 임대인 지위 승계",
    "주택 매매 임대차 승계 보증금 반환",
    "소유권 이전 임대인 지위 승계 대항력",
    "임차주택 양도 보증금반환채무 승계",
]

OWNERSHIP_RECOLLECT_TAG = "중-①소유권_변동모니터링"
OWNERSHIP_LEASE_KEYWORDS = ["임대차", "임차", "보증금", "임대인"]
OWNERSHIP_CHANGE_KEYWORDS = ["승계", "양수", "양도", "매수인", "소유권", "이전"]


def is_ownership_change_lease_related(detail: dict) -> bool:
    """임대차 맥락과 소유권변동(승계) 맥락이 판시사항/판결요지/사건명에 함께 있어야 채택."""
    haystack = " ".join(filter(None, [
        detail.get("판시사항"), detail.get("판결요지"), detail.get("사건명"),
    ]))
    return (any(kw in haystack for kw in OWNERSHIP_LEASE_KEYWORDS)
            and any(kw in haystack for kw in OWNERSHIP_CHANGE_KEYWORDS))


def run_ownership_recollect(oc: str, out_dir: Path):
    raw_dir = out_dir / "raw"
    ref_dir = out_dir / "reference"
    excluded_dir = out_dir / "excluded"
    for d in (raw_dir, ref_dir, excluded_dir):
        d.mkdir(parents=True, exist_ok=True)

    print("\n=== 중-① 소유권변동 재수집 타겟 라운드 ===")

    index_path = out_dir / "index.csv"
    existing_rows = []
    if index_path.exists():
        with open(index_path, encoding="utf-8-sig") as f:
            existing_rows = list(csv.DictReader(f))
    existing_by_pid = {r["판례일련번호"]: r for r in existing_rows}

    query_stats = {q: {"검색후보": 0, "확정": 0} for q in OWNERSHIP_RECOLLECT_QUERIES}
    candidates: dict[str, dict] = {}
    for query in OWNERSHIP_RECOLLECT_QUERIES:
        results = rate_limited_call(search_all_pages_serial, oc, query)
        print(f"  검색: {query} -> {len(results)}건")
        query_stats[query]["검색후보"] = len(results)
        for r in results:
            pid = r["판례일련번호"]
            if pid not in candidates:
                candidates[pid] = {"meta": r, "queries": set()}
            candidates[pid]["queries"].add(query)

    print(f"\n중복 제거 후 검색 후보 {len(candidates)}건. 기존 수집분 스킵 후 상세 조회 시작...")

    new_count = 0
    skipped_existing = 0
    noise_filtered = 0
    for i, (pid, entry) in enumerate(candidates.items(), 1):
        existing_path, existing = find_existing((raw_dir, ref_dir, excluded_dir), pid)
        if existing is not None:
            # 이미 다른 태그로 수집된 판례면 중-① 태그만 병합 (재조회·재분류 없음)
            merged = sorted(set(existing.get("tags", [])) | {OWNERSHIP_RECOLLECT_TAG})
            if merged != sorted(existing.get("tags", [])):
                existing["tags"] = merged
                with open(existing_path, "w", encoding="utf-8") as f:
                    json.dump(existing, f, ensure_ascii=False, indent=2)
                if pid in existing_by_pid:
                    existing_by_pid[pid]["tags"] = ";".join(merged)
            skipped_existing += 1
            continue

        print(f"  [{i}/{len(candidates)}] 상세 조회: {pid} ({entry['meta']['사건명'][:40]})")
        try:
            detail = rate_limited_call(get_precedent_detail, oc, pid)
        except RuntimeError as e:
            print(f"    !! 상세 조회 실패, 스킵: {e}", file=sys.stderr)
            continue

        if not is_ownership_change_lease_related(detail):
            noise_filtered += 1
            continue  # 소유권 관련이나 임대차 승계 쟁점과 무관 — 노이즈로 제외

        for q in entry["queries"]:
            query_stats[q]["확정"] += 1

        grade = grade_precedent(detail)
        if grade == "C":
            print(f"    -> C등급(요지/전문 모두 없음), 목표 등급(A/B) 미달로 제외")
            continue

        target_dir = raw_dir if grade == "A" else ref_dir
        record = {
            "tags": [OWNERSHIP_RECOLLECT_TAG], "grade": grade,
            "meta": entry["meta"], "detail": detail, "근거법": ["주택임대차보호법"],
        }
        with open(target_dir / f"{pid}.json", "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        existing_by_pid[pid] = {
            "판례일련번호": pid, "사건명": entry["meta"].get("사건명"),
            "선고일자": entry["meta"].get("선고일자"), "tags": OWNERSHIP_RECOLLECT_TAG,
            "grade": grade, "근거법": "주택임대차보호법",
        }
        new_count += 1

    with open(index_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["판례일련번호", "사건명", "선고일자", "tags", "grade", "근거법"])
        writer.writeheader()
        writer.writerows(existing_by_pid.values())

    print("\n=== 중-① 소유권변동 재수집 완료 ===")
    print(f"  신규 확정(A/B): {new_count}건 (기존 중복 스킵: {skipped_existing}건, 노이즈 필터 제외: {noise_filtered}건)")
    for query, counts in query_stats.items():
        print(f"    \"{query}\": 검색후보 {counts['검색후보']}건 -> 확정 {counts['확정']}건")
    print(f"  인덱스: {index_path}")


def build_url(base: str, params: dict) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    return f"{base}?{urlencode(clean)}"


def _save_debug(url: str, raw_bytes: bytes, tag: str = ""):
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{int(time.time()*1000)}_{tag}.txt".replace("/", "_")
    with open(DEBUG_DIR / fname, "wb") as f:
        f.write(f"URL: {url}\n\n".encode("utf-8"))
        f.write(raw_bytes)


def fetch_xml(url: str, debug_tag: str = "") -> ET.Element:
    """재시도 로직 포함 XML 요청. 응답이 기대한 구조가 아니면(에러 XML/HTML 등)
    원문을 그대로 예외 메시지에 포함시켜 원인 파악이 가능하게 한다."""
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0 (jeonse-contract-data-collector/1.0)"})
            with urlopen(req, timeout=15) as resp:
                raw = resp.read()

            if DEBUG:
                _save_debug(url, raw, debug_tag)

            try:
                root = ET.fromstring(raw)
            except ET.ParseError:
                # XML이 아닌 응답(HTML 에러페이지 등)이 온 경우 — 원문 앞부분을 그대로 보여줌
                preview = raw[:500].decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"XML 파싱 실패 — API가 XML이 아닌 응답을 반환함.\n"
                    f"URL: {url}\n응답 미리보기:\n{preview}"
                )

            # law.go.kr가 인증/권한 오류 시 반환하는 형태 체크
            # (알려진 패턴: <OpenApiService><error>... 또는 루트에 에러 코드/메시지 포함)
            err_code = root.findtext(".//code") or root.findtext(".//errorCode")
            err_msg = root.findtext(".//message") or root.findtext(".//errorMsg")
            if err_code or (root.tag not in ("PrecSearch", "PrecService", "LawService")
                            and root.findtext("totalCnt") is None
                            and root.find("prec") is None
                            and not list(root)):
                raw_preview = raw[:500].decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"API 응답에서 정상 구조(PrecSearch 등)를 찾을 수 없음 — 인증(OC) 또는 "
                    f"권한(IP 화이트리스트) 문제일 가능성이 높음.\n"
                    f"루트 태그: <{root.tag}> / 에러코드: {err_code} / 메시지: {err_msg}\n"
                    f"URL: {url}\n응답 미리보기:\n{raw_preview}"
                )

            return root
        except (URLError, HTTPError) as e:
            last_err = e
            print(f"  [재시도 {attempt}/{MAX_RETRIES}] 요청 실패: {e}", file=sys.stderr)
            time.sleep(RETRY_BACKOFF_SEC * attempt)
        except RuntimeError as e:
            # 구조적 오류(인증/파싱)는 재시도해도 동일할 가능성이 높으므로 즉시 표면화
            raise
    raise RuntimeError(f"요청 최종 실패: {url}\n원인: {last_err}")


def search_precedents(oc: str, query: str, jo: str = None, page: int = 1) -> tuple[list[dict], int]:
    """
    lawSearch.do 호출. 반환: (해당 페이지의 prec 리스트, totalCnt)
    """
    params = {
        "OC": oc,
        "target": "prec",
        "type": "XML",
        "query": query,
        "search": 2,          # 본문검색 (필수 — 제목검색만 하면 대부분 누락됨)
        "display": PAGE_DISPLAY,
        "page": page,
    }
    if jo:
        params["JO"] = jo

    url = build_url(BASE_SEARCH_URL, params)
    root = fetch_xml(url, debug_tag=f"search_{query[:15]}")

    total_cnt = int((root.findtext("totalCnt") or "0"))
    results = []
    for prec in root.findall("prec"):
        results.append({
            "판례일련번호": prec.findtext("판례일련번호"),
            "사건명": (prec.findtext("사건명") or "").strip(),
            "사건번호": prec.findtext("사건번호"),
            "선고일자": prec.findtext("선고일자"),
            "법원명": prec.findtext("법원명"),
            "사건종류명": prec.findtext("사건종류명"),
            "판결유형": prec.findtext("판결유형"),
        })
    return results, total_cnt


def search_all_pages(oc: str, query: str, jo: str = None) -> list[dict]:
    """페이지네이션 처리하여 해당 쿼리의 전체 결과 수집"""
    all_results = []
    page = 1
    while True:
        results, total_cnt = search_precedents(oc, query, jo, page)
        all_results.extend(results)
        time.sleep(REQUEST_DELAY_SEC)
        if len(all_results) >= total_cnt or not results:
            break
        page += 1
    return all_results


def get_precedent_detail(oc: str, prec_id: str) -> dict:
    """lawService.do 호출하여 판례 상세(판시사항/판결요지/참조조문/전문) 조회"""
    params = {"OC": oc, "target": "prec", "ID": prec_id, "type": "XML"}
    url = build_url(BASE_SERVICE_URL, params)
    root = fetch_xml(url, debug_tag=f"detail_{prec_id}")

    def text(tag):
        el = root.find(tag)
        return (el.text or "").strip() if el is not None and el.text else None

    detail = {
        "판례일련번호": prec_id,
        "사건명": text("사건명"),
        "사건번호": text("사건번호"),
        "선고일자": text("선고일자"),
        "법원명": text("법원명"),
        "판시사항": text("판시사항"),
        "판결요지": text("판결요지"),
        "참조조문": text("참조조문"),
        "참조판례": text("참조판례"),
        "전문": text("판례내용"),
    }
    return detail


def grade_precedent(detail: dict) -> str:
    """
    판례 상세 데이터의 활용 등급을 매긴다.
    A: 판시사항 또는 판결요지 존재 → 정상 청킹/임베딩 대상
    B: 둘 다 없지만 전문은 존재 → 임베딩 보류, 참조 전용(각주용) 메타데이터로만 저장
    C: 전문까지 없거나 실질적 내용 없음 → 미적재 대상
    """
    has_summary = bool(detail.get("판시사항")) or bool(detail.get("판결요지"))
    has_full_text = bool(detail.get("전문")) and len(detail.get("전문", "")) > 30

    if has_summary:
        return "A"
    if has_full_text:
        return "B"
    return "C"


def find_existing(dirs: tuple[Path, ...], pid: str) -> tuple[Path, dict] | tuple[None, None]:
    """이미 raw/reference/excluded 중 어느 폴더에든 저장돼 있으면 그 경로와 내용을 반환"""
    for d in dirs:
        p = d / f"{pid}.json"
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return p, json.load(f)
    return None, None


def run_collection(oc: str, out_dir: Path, include_track_a: bool = True):
    raw_dir = out_dir / "raw"           # A등급: 정상 청킹/임베딩 대상
    ref_dir = out_dir / "reference"     # B등급: 참조 전용 (임베딩 보류)
    excluded_dir = out_dir / "excluded" # C등급: 미적재, 재수집 후보
    for d in (raw_dir, ref_dir, excluded_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 판례일련번호 -> {"tags": set(), "meta": {...}}
    collected: dict[str, dict] = {}

    def register(tag: str, prec_meta: dict):
        pid = prec_meta["판례일련번호"]
        if pid not in collected:
            collected[pid] = {"tags": set(), "meta": prec_meta}
        collected[pid]["tags"].add(tag)

    # 법령명 정확 매칭 확인을 위해 미리 상세조회한 결과 캐시 (아래 본 조회 루프에서 재사용)
    pre_fetched_details: dict[str, dict] = {}

    # --- Track A: 확인용 ---
    if include_track_a:
        print("\n=== Track A: 전세사기피해자법 직접판례 확인 ===")
        for q in TRACK_A_QUERIES:
            print(f"  검색: {q['query']}")
            results = search_all_pages(oc, q["query"], q.get("JO"))
            print(f"    -> {len(results)}건 (형태소 매칭 후보, 법령명 정확 인용 여부 확인 중)")
            genuine = 0
            for r in results:
                pid = r["판례일련번호"]
                try:
                    detail = get_precedent_detail(oc, pid)
                except RuntimeError as e:
                    print(f"    !! 상세 조회 실패, 스킵: {pid} ({e})", file=sys.stderr)
                    continue
                time.sleep(REQUEST_DELAY_SEC)
                if is_track_a_genuine(detail):
                    register(q["tag"], r)
                    pre_fetched_details[pid] = detail
                    genuine += 1
            print(f"    -> 법령명 정확 인용 확인된 건: {genuine}건 (나머지는 형태소 노이즈로 제외)")

    # --- Track B: 본체 ---
    print("\n=== Track B: 기존 법령 기반 판례 수집 ===")
    for tag, query_list in TRACK_B_QUERIES.items():
        for q in query_list:
            print(f"  [{tag}] 검색: {q['query']}")
            results = search_all_pages(oc, q["query"], q.get("JO"))
            print(f"    -> {len(results)}건")
            for r in results:
                register(tag, r)

    print(f"\n중복 제거 후 총 {len(collected)}건의 고유 판례 수집됨. 상세 조회 시작...")

    # --- 상세 조회 및 등급별 저장 ---
    index_rows = []
    grade_counts = {"A": 0, "B": 0, "C": 0}

    for i, (pid, entry) in enumerate(collected.items(), 1):
        tags = sorted(entry["tags"])
        existing_path, existing = find_existing((raw_dir, ref_dir, excluded_dir), pid)

        if existing is not None:
            # 이미 수집된 판례면 상세 재조회 없이 태그만 갱신 (등급/폴더는 그대로 유지)
            merged_tags = sorted(set(existing.get("tags", [])) | set(tags))
            existing["tags"] = merged_tags
            with open(existing_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            grade = existing.get("grade", "?")
            grade_counts[grade] = grade_counts.get(grade, 0) + 1
            index_rows.append({
                "판례일련번호": pid, "사건명": existing["meta"].get("사건명"),
                "선고일자": existing["meta"].get("선고일자"), "tags": ";".join(merged_tags),
                "grade": grade, "근거법": existing.get("근거법", ""),
            })
            continue

        if pid in pre_fetched_details:
            detail = pre_fetched_details[pid]
        else:
            print(f"  [{i}/{len(collected)}] 상세 조회: {pid} ({entry['meta']['사건명'][:40]})")
            try:
                detail = get_precedent_detail(oc, pid)
            except RuntimeError as e:
                print(f"    !! 상세 조회 실패, 스킵: {e}", file=sys.stderr)
                continue
            time.sleep(REQUEST_DELAY_SEC)

        grade = grade_precedent(detail)
        grade_counts[grade] += 1
        target_dir = {"A": raw_dir, "B": ref_dir, "C": excluded_dir}[grade]

        record = {"tags": tags, "grade": grade, "meta": entry["meta"], "detail": detail}
        out_path = target_dir / f"{pid}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        if grade == "C":
            print(f"    -> C등급(요지/전문 모두 없음), excluded/에 저장 — 재수집 후보")

        index_rows.append({
            "판례일련번호": pid, "사건명": entry["meta"].get("사건명"),
            "선고일자": entry["meta"].get("선고일자"), "tags": ";".join(tags),
            "grade": grade, "근거법": "",
        })

    # --- 인덱스 CSV 저장 (grade, 근거법 컬럼 포함) ---
    index_path = out_dir / "index.csv"
    with open(index_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["판례일련번호", "사건명", "선고일자", "tags", "grade", "근거법"])
        writer.writeheader()
        writer.writerows(index_rows)

    print(f"\n완료.")
    print(f"  A등급(정상 임베딩 대상): {grade_counts['A']}건 -> {raw_dir}/")
    print(f"  B등급(참조 전용, 임베딩 보류): {grade_counts['B']}건 -> {ref_dir}/")
    print(f"  C등급(미적재, 재수집 후보): {grade_counts['C']}건 -> {excluded_dir}/")
    print(f"  인덱스: {index_path}")


def sanity_check(oc: str):
    """본 수집 전에 단일 쿼리로 인증/네트워크 상태만 빠르게 확인"""
    global DEBUG
    DEBUG = True
    print("=== 인증/연결 상태 확인 (단일 쿼리 테스트) ===")
    print(f"OC={oc} 로 '다가구주택 선순위 임차보증금' 검색 시도...")
    try:
        results, total_cnt = search_precedents(oc, "다가구주택 선순위 임차보증금")
        print(f"성공: totalCnt={total_cnt}, 반환건수={len(results)}")
        if total_cnt == 0:
            print("  -> API 통신은 됐지만 0건. 쿼리/파라미터 문제일 수 있음.")
    except RuntimeError as e:
        print("실패. 아래 원인 메시지 확인:\n")
        print(str(e))
        print(f"\n(원본 응답은 {DEBUG_DIR.resolve()}/ 에 저장됨)")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="D파트 판례 자동 수집 (Track A/B)")
    parser.add_argument("--oc", required=True, help="law.go.kr Open API 인증 ID (예: Whitecube1)")
    parser.add_argument("--out", default="./data", help="출력 디렉토리 (기본: ./data)")
    parser.add_argument("--skip-track-a", action="store_true", help="Track A 확인 쿼리 생략")
    parser.add_argument("--debug", action="store_true", help="원본 API 응답을 ./debug_raw/ 에 저장")
    parser.add_argument("--check", action="store_true",
                         help="본 수집 없이 단일 쿼리로 인증/연결 상태만 확인하고 종료")
    parser.add_argument("--track-c", action="store_true",
                         help="Track A/B 본 수집 대신 근거법 보강용 Track C(형법/공인중개사법/신탁법/채무자회생법)만 병렬 수집")
    parser.add_argument("--trust-law-recollect", action="store_true",
                         help="Track A/B/C 대신 신탁법 재수집 타겟 라운드(작업지시서: 신탁법재수집)만 실행")
    parser.add_argument("--ownership-recollect", action="store_true",
                         help="Track A/B/C 대신 중-①소유권변동 재수집 타겟 라운드(작업단위 42)만 실행")
    args = parser.parse_args()

    global DEBUG
    DEBUG = args.debug

    if args.check:
        sanity_check(args.oc)
        return

    out_dir = Path(args.out)

    if args.track_c:
        run_track_c(args.oc, out_dir)
        return

    if args.trust_law_recollect:
        run_trust_law_recollect(args.oc, out_dir)
        return

    if args.ownership_recollect:
        run_ownership_recollect(args.oc, out_dir)
        return

    run_collection(args.oc, out_dir, include_track_a=not args.skip_track_a)


if __name__ == "__main__":
    main()
