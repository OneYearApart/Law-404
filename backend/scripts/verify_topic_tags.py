"""topic_tags 어휘 정합성 검증 + 근거자료 커버리지 매트릭스 (작업단위 34).

general_scenario의 검색 전체가 `topic_tags && ['{항목키}']` 문자열 완전일치에 물려 있다.
어휘 소스가 세 군데(schemas.GENERAL_TOPIC_LABELS / links_d.TOPIC_TAG_KEYWORDS /
판례 수집 시점의 index.csv tags)로 흩어져 있어, 한 글자만 어긋나도 검색이 조용히 0건이
되고 조문 몇 건만으로 답변이 생성되어 티가 나지 않는다. 그 불일치를 드러내는 것이 목적.

실행: python -m scripts.verify_topic_tags  (backend/ 에서)
0건 항목이 있으면 exit code 1.
"""
import sys

from sqlalchemy import text

from app.core.config import get_engine
from app.graph.parts.d_part.schemas import GENERAL_TOPIC_LABELS, SPECIAL_CASE_CATEGORIES
from app.rag.ingestion.links_d import TOPIC_TAG_KEYWORDS

# special_cases.py는 현재 RAG를 타지 않고 _SPECIAL_CASE_GUIDANCE 하드코딩 문구만 반환한다.
# 아래는 "RAG로 전환한다면 어느 태그를 쓰게 되는가"를 보여주기 위한 참고 매핑 (프로덕션 경로 아님).
SPECIAL_CASE_TAG_HINT: dict[str, str] = {
    "임대인 사망/파산": "트리거-임대인사망파산",
    "신탁사기": "전-⑤신탁사기",
    "다가구주택": "전-③다가구_선순위보증금",
    "공인중개사 허위고지": "전-⑥공인중개사_허위고지",
}

# "상황적용" 층을 뒷받침할 source_type (단위 40에서 신설 예정 — 현재는 존재하지 않음).
SITUATION_SOURCE_TYPES = ("상담사례", "FAQ")


def _tag_counts() -> dict[tuple[str, str], int]:
    with get_engine().connect() as conn:
        rows = conn.execute(text(
            "SELECT unnest(topic_tags) AS tag, source_type, count(*)"
            " FROM d_part_embeddings GROUP BY 1, 2"
        )).all()
    return {(tag, source_type): n for tag, source_type, n in rows}


def _source_type_totals() -> dict[str, int]:
    with get_engine().connect() as conn:
        return dict(conn.execute(text(
            "SELECT source_type, count(*) FROM d_part_embeddings GROUP BY 1"
        )).all())


def _row(counts: dict[tuple[str, str], int], tag: str) -> tuple[int, int, int]:
    case_law = counts.get((tag, "판례"), 0)
    hug = counts.get((tag, "HUG사례집"), 0) + counts.get((tag, "HUG규정"), 0)
    situation = sum(counts.get((tag, st), 0) for st in SITUATION_SOURCE_TYPES)
    return case_law, hug, situation


def main() -> int:
    counts = _tag_counts()
    db_tags = {tag for tag, _ in counts}

    print("=" * 74)
    print("어휘 정합성 — GENERAL_TOPIC_LABELS(정본) 대비")
    print("=" * 74)
    missing_keywords = set(GENERAL_TOPIC_LABELS) - set(TOPIC_TAG_KEYWORDS)
    extra_keywords = set(TOPIC_TAG_KEYWORDS) - set(GENERAL_TOPIC_LABELS)
    print(f"  TOPIC_TAG_KEYWORDS에 없는 정본 키 : {sorted(missing_keywords) or '없음'}")
    print(f"  정본에 없는 TOPIC_TAG_KEYWORDS 키 : {sorted(extra_keywords) or '없음'}")
    print("    (트리거 계열은 일반 13개 항목 밖이라 정상 — 단위 34의 '별도 상수 분리' 대상)")

    print()
    print("=" * 74)
    print("커버리지 매트릭스 — 행: 라우팅 카테고리 / 열: 응답 3층 근거자료 건수")
    print("=" * 74)
    print(f"  {'카테고리':<26} {'원문(법령)':>10} {'해설(판례)':>10} {'해설(HUG)':>10} {'상황적용':>8}")
    print("  " + "-" * 70)

    zero_coverage: list[str] = []

    print("  [general_topic — 13개]")
    for key in GENERAL_TOPIC_LABELS:
        case_law, hug, situation = _row(counts, key)
        in_db = key in db_tags
        if not in_db:
            zero_coverage.append(key)
        flag = "" if in_db else "   <-- 태그 0건"
        # 법령원문은 topic_tags를 쓰지 않고 벡터검색으로만 접근하므로 항목별 건수가 없다.
        print(f"  {key:<26} {'벡터':>10} {case_law:>10} {hug:>10} {situation:>8}{flag}")

    print("  [special_case — 4개] (현재 RAG 미사용, 하드코딩 안내문)")
    for name in SPECIAL_CASE_CATEGORIES:
        tag = SPECIAL_CASE_TAG_HINT[name]
        case_law, hug, situation = _row(counts, tag)
        print(f"  {name:<26} {'벡터':>10} {case_law:>10} {hug:>10} {situation:>8}   (태그: {tag})")

    print("  [victim_interview] 전세사기피해자법 제3조 직접 매핑 + 링크 조인 (topic_tags 미사용)")
    print("  [open_qa]          무제약 벡터검색 (topic_tags 미사용)")

    print()
    print("=" * 74)
    print("source_type 총계")
    print("=" * 74)
    for st, n in sorted(_source_type_totals().items(), key=lambda kv: -kv[1]):
        print(f"  {st:<12} {n:>5}")
    absent = [st for st in SITUATION_SOURCE_TYPES if st not in _source_type_totals()]
    if absent:
        print(f"  * 상황적용 층 부재 — source_type {absent} 없음 (단위 40 대상)")

    print()
    if zero_coverage:
        print(f"FAIL: 근거자료 0건 항목 {len(zero_coverage)}개 — {zero_coverage}")
        print("  -> 이 항목들은 판례/HUG 검색이 항상 0건이고 조문만으로 답변이 생성된다.")
        print("     단위 42(판례 타깃 재수집) / 단위 34-4(자료없음 응답 모드)의 대상.")
        return 1

    print("OK: 13개 항목 전부 근거자료 보유")
    return 0


if __name__ == "__main__":
    sys.exit(main())
