# -*- coding: utf-8 -*-
"""
D파트 "상황적용" 층 수집 — 찾기쉬운 생활법령정보(easylaw.go.kr) (작업단위 40, csmSeq 복수화 50)
==========================================================================
"원문 -> 해설 -> 상황적용" 3단 구조에서 비어있던 "상황적용" 레이어를, 법제처
찾기쉬운 생활법령정보의 책자형 콘텐츠(csmSeq별)로 채운다. 기본값은 '전세사기 피해자
지원'(csmSeq=1972)이며, --csmSeq를 복수로 넘겨 전세/임대차 관련 booklet을 추가 수집한다.

지시서 1순위였던 대한법률구조공단 상담사례(klac.or.kr/legalinfo/)는 robots.txt가
/legalinfo/ 전체를 Disallow하여 수집 제외. easylaw는 User-agent:* 에 대한 Disallow가
없어(구글봇 검색결과 경로 2개만 제한) CnpClsMain.laf 본문 수집이 허용된다.

수집 방식:
- 랜딩 페이지의 좌측 메뉴에서 (ccfNo,cciNo,cnpClsNo) 리프 조합을 동적으로 발견
- 각 리프의 본문(<div id="ovDiv">)만 추출 (네비게이션 chrome 제외)
- 결과: {out}/easylaw_{csmSeq}.json (csmSeq=1972는 기존 파일명 유지, 페이지 단위 리스트)

크롤링 매너: 요청 간 딜레이, Mozilla UA. 출처(공공누리, 법제처) metadata에 표기.

사용법:
    python collect_easylaw.py --out "C:\\...\\easylaw"                 # 기본 1972
    python collect_easylaw.py --csmSeq 1972 --csmSeq 1170 --out "..."   # 복수 booklet

주의: 본 스크립트는 개발용 수집 도구라 bs4를 쓴다(런타임 인제스천 파서 easylaw_docs_d.py는
JSON만 읽어 bs4 비의존). collect_statutes.py와 동일하게 산출물 JSON이 repo 밖에 남는다.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

BASE = "https://www.easylaw.go.kr"
DEFAULT_CSM_SEQ = 1972  # 전세사기 피해자 지원
UA = "Mozilla/5.0 (jeonse-easylaw-collector/1.0)"
REQUEST_DELAY_SEC = 1.0

# csmSeq별 출력 파일명 — 1972는 작업단위 40 산출물 파일명을 유지(재수집 시 덮어씀),
# 그 외는 easylaw_{csmSeq}.json. easylaw_docs_d.py가 디렉터리 내 *.json을 모두 읽는다.
_OUT_NAME_OVERRIDE = {1972: "전세사기_피해자_지원.json"}


def _out_name(csm_seq: int) -> str:
    return _OUT_NAME_OVERRIDE.get(csm_seq, f"easylaw_{csm_seq}.json")


def fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


def discover_leaves(landing_html: str, csm_seq: int) -> list[tuple[str, str, str]]:
    leaf_re = re.compile(
        rf"csmSeq={csm_seq}[^\"'<>]*?ccfNo=(\d+)[^\"'<>]*?cciNo=(\d+)[^\"'<>]*?cnpClsNo=(\d+)"
    )
    return sorted(
        set(leaf_re.findall(landing_html)), key=lambda t: tuple(int(x) for x in t)
    )


_UI_NOISE = {"인쇄체크", "인쇄", "목록", "이전", "다음"}


def _clean_text(el) -> str:
    # 표는 셀을 " | "로, 그 외는 줄바꿈으로 텍스트화
    for table in el.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
            if any(cells):
                rows.append(" | ".join(cells))
        table.replace_with("\n".join(rows))
    lines = [
        l
        for l in el.get_text("\n", strip=True).split("\n")
        if l.strip() not in _UI_NOISE
    ]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return text.strip()


def parse_leaf(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    title = (
        title_tag.get_text(strip=True).split("(본문)")[0].strip() if title_tag else ""
    )
    content_el = soup.select_one("#ovDiv")
    if content_el is None:
        return None
    content = _clean_text(content_el)
    if len(content) < 40:
        return None
    return {"title": title, "content": content}


def run(out_dir: Path, csm_seq: int):
    out_dir.mkdir(parents=True, exist_ok=True)
    landing = f"{BASE}/CSP/CnpClsMain.laf?popMenu=ov&csmSeq={csm_seq}&ccfNo=1&cciNo=1&cnpClsNo=1"
    print(f"[csmSeq={csm_seq}] 랜딩에서 리프 페이지 발견: {landing}")
    leaves = discover_leaves(fetch(landing), csm_seq)
    print(f"  발견한 리프 {len(leaves)}개: {leaves}")
    time.sleep(REQUEST_DELAY_SEC)

    pages = []
    for ccf, cci, cnp in leaves:
        url = f"{BASE}/CSP/CnpClsMain.laf?popMenu=ov&csmSeq={csm_seq}&ccfNo={ccf}&cciNo={cci}&cnpClsNo={cnp}"
        try:
            leaf = parse_leaf(fetch(url))
        except Exception as e:
            print(f"  [실패] {ccf}.{cci}.{cnp}: {e}", file=sys.stderr)
            leaf = None
        if leaf is None:
            print(f"  [스킵] {ccf}.{cci}.{cnp} (본문 없음/짧음)")
        else:
            leaf.update({"ccfNo": ccf, "cciNo": cci, "cnpClsNo": cnp, "url": url})
            pages.append(leaf)
            print(
                f"  [수집] {ccf}.{cci}.{cnp} '{leaf['title']}' ({len(leaf['content'])}자)"
            )
        time.sleep(REQUEST_DELAY_SEC)

    record = {
        "출처": f"법제처 찾기쉬운 생활법령정보(easylaw.go.kr) (csmSeq={csm_seq})",
        "이용조건": "공공누리 — 출처표기",
        "항목유형": "책자",
        "csmSeq": csm_seq,
        "페이지수": len(pages),
        "페이지": pages,
    }
    out_path = out_dir / _out_name(csm_seq)
    out_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"=== [csmSeq={csm_seq}] 완료: {len(pages)}페이지 -> {out_path} ===\n")


def main():
    p = argparse.ArgumentParser(description="easylaw 생활법령 수집 (작업단위 40/50)")
    p.add_argument("--out", default="./easylaw", help="출력 디렉토리")
    p.add_argument(
        "--csmSeq",
        type=int,
        action="append",
        dest="csm_seqs",
        help="수집할 booklet csmSeq (복수 지정 가능, 미지정 시 1972)",
    )
    args = p.parse_args()
    csm_seqs = args.csm_seqs or [DEFAULT_CSM_SEQ]
    for csm_seq in csm_seqs:
        run(Path(args.out), csm_seq)


if __name__ == "__main__":
    main()
