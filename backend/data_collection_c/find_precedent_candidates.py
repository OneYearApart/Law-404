"""
이 스크립트는 본문(판례내용)을 가져오지 않습니다 — 목록 정보만으로
질문과 사실관계가 맞는 판례를 사람이 골라내는 용도입니다.
(수백 건을 다 수집하지 않기 위한 필터링 단계)
"""

import json
import os
import time
from common import _get, LIST_URL, API_KEY

ORG_대법원 = "400201"

# 역산표 카테고리 3 — 질문별 검색 키워드
QUESTION_KEYWORDS = {
    "Q1_보증금못받음":         "보증금반환",
    "Q2_임차권등기명령":       "임차권등기명령",
    "Q3_경매배당":             "배당요구",
    "Q4_소액보증금최우선변제": "소액임차인",
}


def fetch_list(keyword, org=ORG_대법원, display=10):
    params = {
        "OC": API_KEY,
        "target": "prec",
        "query": keyword,
        "org": org,
        "display": display,
        "page": 1,
        "search": 2,  # 1=사건명(제목)만 검색, 2=본문(판시사항 등) 검색
        "type": "JSON",
    }
    resp = _get(LIST_URL, params)
    return resp.json().get("PrecSearch", {}).get("prec", [])


def main():
    os.makedirs("data", exist_ok=True)
    all_candidates = {}

    for qid, keyword in QUESTION_KEYWORDS.items():
        print(f"\n🔍 [{qid}] 키워드: '{keyword}' (대법원, 상위 10건만)")
        items = fetch_list(keyword)
        if isinstance(items, dict):
            items = [items]

        candidates = []
        for item in items:
            if item.get("사건종류명", "") != "민사":
                continue  # 세무/형사/일반행정 등 관련 없는 사건 제외
            candidates.append({
                "판례일련번호": item.get("판례일련번호", ""),
                "사건명":       item.get("사건명", ""),
                "사건번호":     item.get("사건번호", ""),
                "선고일자":     item.get("선고일자", ""),
                "법원명":       item.get("법원명", ""),
                "사건종류명":   item.get("사건종류명", ""),
            })
            print(f"   - {item.get('사건명','')[:40]} / {item.get('사건번호','')} / {item.get('선고일자','')}")

        all_candidates[qid] = candidates
        time.sleep(0.3)

    path = "data/precedent_candidates_카테고리3.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(all_candidates, f, ensure_ascii=False, indent=2)

    print(f"\n📦 후보 목록 저장 완료 → {path}")
    print("   이 중 질문당 1~2건을 골라 collect_selected_precedents.py의")
    print("   SELECTED_CASES에 판례일련번호를 채워 넣으세요.")


if __name__ == "__main__":
    main()