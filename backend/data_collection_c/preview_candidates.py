"""
설명 태그가 없어 관련성을 판단하기 어려운 판례들의
판시사항만 미리 확인합니다. (전체 본문은 아직 저장 안 함)
"""

from common import _get, DETAIL_URL, API_KEY

# 관련성 확인이 필요한 판례일련번호를 여기에 넣으세요
CHECK_IDS = [
    "221753",  # 배당이의
    "240307",  # 부당이득금·보증금반환
    "223315",  # 공제금등청구의소
]


def preview(prec_id):
    params = {"OC": API_KEY, "target": "prec", "ID": prec_id, "type": "JSON"}
    resp = _get(DETAIL_URL, params)
    try:
        prec = resp.json().get("PrecService", {})
        return {
            "사건명":   prec.get("사건명", ""),
            "판시사항": prec.get("판시사항", "")[:400],  # 앞부분만
        }
    except Exception:
        return None


def main():
    for pid in CHECK_IDS:
        info = preview(pid)
        print(f"\n{'='*60}")
        print(f"판례일련번호: {pid}")
        if info:
            print(f"사건명: {info['사건명']}")
            print(f"판시사항: {info['판시사항']}")
        else:
            print("조회 실패")


if __name__ == "__main__":
    main()