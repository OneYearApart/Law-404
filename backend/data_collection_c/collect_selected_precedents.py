"""find_precedent_candidates.py 결과를 보고 직접 고른 판례만 본문을 수집합니다.
질문당 1~2건으로 제한하세요 (수백 건 수집 방지).
"""

import json
import os
import time
from common import _get, DETAIL_URL, API_KEY

SELECTED_CASES = {
    "Q1_보증금못받음": [
        "241081",
        "615961",
    ],
    "Q2_임차권등기명령": [
        "605771",
    ],
    "Q3_경매배당": [
        "618185",
    ],
    "Q4_소액보증금최우선변제": [
        "240307",
    ],
}


def fetch_case_detail(prec_id):
    params = {"OC": API_KEY, "target": "prec", "ID": prec_id, "type": "JSON"}
    resp = _get(DETAIL_URL, params)

    if "미신청된" in resp.text or "<!DOCTYPE" in resp.text:
        return None

    try:
        prec = resp.json().get("PrecService", {})
        return {
            "판례일련번호": prec_id,
            "사건명":       prec.get("사건명", ""),
            "사건번호":     prec.get("사건번호", ""),
            "선고일자":     prec.get("선고일자", ""),
            "법원명":       prec.get("법원명", ""),
            "판시사항":     prec.get("판시사항", ""),
            "판결요지":     prec.get("판결요지", ""),
            "판례내용":     prec.get("판례내용", ""),
            "참조조문":     prec.get("참조조문", ""),
            "참조판례":     prec.get("참조판례", ""),
        }
    except Exception:
        return None


def main():
    os.makedirs("data", exist_ok=True)
    result = {}

    for qid, ids in SELECTED_CASES.items():
        if not ids:
            print(f"⚠️  [{qid}] 선정된 판례가 없습니다 — 건너뜁니다.")
            continue

        cases = []
        for prec_id in ids:
            detail = fetch_case_detail(prec_id)
            if detail:
                detail["question_id"] = qid
                detail["category_tag"] = 3  # 카테고리 3: 보증금 반환, 경매·배당
                cases.append(detail)
                print(f"✅ [{qid}] {detail['사건명'][:40]} 수집 완료")
            else:
                print(f"❌ [{qid}] {prec_id} 본문 조회 실패")
            time.sleep(0.3)

        result[qid] = cases

    path = "data/precedents_selected_카테고리3.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n📦 최종 수집 완료 → {path}")


if __name__ == "__main__":
    main()