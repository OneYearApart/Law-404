"""
역산표(카테고리 3) 기준 확정 조문만 수집합니다.
조문은 이미 확정된 상태라 바로 실행 가능합니다.

⚠️ 법령 API 응답의 '조문' 배열 경로/필드명은 실제로 한 번 실행해서
data/주택임대차보호법_raw.json 을 열어본 뒤 확인이 필요합니다.
아래 extract_target_articles()는 일반적인 구조를 가정한 것이며,
실제 키 이름이 다르면 그 부분만 맞춰 수정하면 됩니다.
"""

import json
import os
from common import _get, LIST_URL, DETAIL_URL, API_KEY

LAW_NAME = "주택임대차보호법"

# 역산표 카테고리 3에서 확정된 조문 — (조문번호, 조문가지번호) 형태로 정확히 지정
# 조문가지번호가 없는 본조는 None
TARGET_ARTICLES = [
    ("3", None),   # 제3조
    ("3", "2"),    # 제3조의2
    ("3", "3"),    # 제3조의3
    ("8", None),   # 제8조
]


def find_law_id(law_name):
    params = {"OC": API_KEY, "target": "law", "query": law_name, "type": "JSON"}
    resp = _get(LIST_URL, params)
    data = resp.json()
    laws = data.get("LawSearch", {}).get("law", [])
    if not laws:
        raise ValueError(f"'{law_name}' 검색 결과 없음")
    if isinstance(laws, dict):
        laws = [laws]
    # 여러 건이면 첫 번째(현행)를 사용 — 시행일자가 다른 버전이 섞여있을 수 있으니
    # data/law_search_raw.json으로 목록을 확인하고 필요시 인덱스를 바꾸세요.
    return laws[0]


def fetch_law_full_text(law_id):
    params = {"OC": API_KEY, "target": "law", "MST": law_id, "type": "JSON"}
    resp = _get(DETAIL_URL, params)
    return resp.json()


def _flatten_hang(hang_list):
    """항(①②③...) 안의 호·목까지 텍스트로 이어붙임"""
    if isinstance(hang_list, dict):
        hang_list = [hang_list]

    texts = []
    for hang in hang_list:
        if "항내용" in hang:
            texts.append(hang["항내용"])
        ho_list = hang.get("호", [])
        if isinstance(ho_list, dict):
            ho_list = [ho_list]
        for ho in ho_list:
            if "호내용" in ho:
                texts.append(ho["호내용"])
            mok_list = ho.get("목", [])
            if isinstance(mok_list, dict):
                mok_list = [mok_list]
            for mok in mok_list:
                if "목내용" in mok:
                    texts.append(mok["목내용"])
    return "\n".join(texts)


def extract_target_articles(law_json, target_articles):
    articles = (
        law_json.get("법령", {})
        .get("조문", {})
        .get("조문단위", [])
    )
    if isinstance(articles, dict):
        articles = [articles]

    matched = []
    for art in articles:
        조문번호 = str(art.get("조문번호", ""))
        조문가지번호 = art.get("조문가지번호")  # 없으면 None
        조문제목 = art.get("조문제목", "")
        조문제목행 = art.get("조문내용", "")  # 항이 있는 조문은 여기 제목만 들어있음

        # 항이 있으면 그 안의 실제 내용을 합치고, 없으면 조문내용을 그대로 사용
        hang = art.get("항")
        if hang:
            본문 = 조문제목행 + "\n" + _flatten_hang(hang)
        else:
            본문 = 조문제목행

        for target_num, target_branch in target_articles:
            if 조문번호 != target_num:
                continue
            if target_branch is None and not 조문가지번호:
                matched.append({
                    "조문번호": 조문번호,
                    "조문제목": 조문제목,
                    "조문내용": 본문,
                })
            elif target_branch is not None and 조문가지번호 == target_branch:
                matched.append({
                    "조문번호": 조문번호,
                    "조문가지번호": 조문가지번호,
                    "조문제목": 조문제목,
                    "조문내용": 본문,
                })
    return matched


def main():
    os.makedirs("data", exist_ok=True)

    print(f"🔍 '{LAW_NAME}' 법령 검색 중...")
    law = find_law_id(LAW_NAME)
    law_id = law.get("법령일련번호") or law.get("MST")
    print(f"✅ 법령ID: {law_id} / {law.get('법령명한글', LAW_NAME)}")

    full = fetch_law_full_text(law_id)

    raw_path = "data/주택임대차보호법_raw.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(full, f, ensure_ascii=False, indent=2)
    print(f"📦 원문 저장 완료 → {raw_path}")

    matched = extract_target_articles(full, TARGET_ARTICLES)

    if matched:
        out_path = "data/statutes_카테고리3.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(matched, f, ensure_ascii=False, indent=2)
        print(f"✅ 대상 조문 {len(matched)}건 추출 완료 → {out_path}")
        for m in matched:
            print(f"   - {m['조문번호']} {m['조문제목']}")
    else:
        print("⚠️ 자동 추출 실패 — data/주택임대차보호법_raw.json 구조를 열어 필드명을 확인 후")
        print("   extract_target_articles() 안의 키 이름을 맞춰 다시 실행하세요.")


if __name__ == "__main__":
    main()