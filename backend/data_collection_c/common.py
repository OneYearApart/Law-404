import os
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("LAW_API_KEY")

LIST_URL = "https://www.law.go.kr/DRF/lawSearch.do"
DETAIL_URL = "https://www.law.go.kr/DRF/lawService.do"

if not API_KEY:
    raise SystemExit("❌ .env 파일에 LAW_API_KEY가 없습니다.")


def _get(url, params):
    resp = requests.get(url, params=params)
    resp.encoding = "utf-8"

    # 디버그: JSON이 아닌 응답이 오면 원인을 바로 확인
    if not resp.text.strip().startswith("{"):
        print("⚠️  JSON이 아닌 응답이 왔습니다.")
        print(f"   status_code: {resp.status_code}")
        print(f"   요청 URL: {resp.url}")
        print(f"   응답 앞부분: {resp.text[:300]}")

    return resp