"""
D파트 검색 거리(distance) 분포 실측 스크립트.

로컬 DB(d_part_embeddings)에 임베딩이 적재된 상태에서 backend/ 기준 수동 실행:
    python -m scripts.bench_d_part_distance

retrievers/d_part.py의 _MAX_DISTANCE(0.65)를 어떤 근거로 정했는지 재현한다.
관련 질의와 무관 질의의 거리 분포가 갈라지는 구간을 확인하는 용도.
프로덕션 코드 경로에는 포함되지 않음.
"""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")

from app.rag.retrievers.d_part import _MAX_DISTANCE, DPartRetriever

TOP_K = 3

RELATED_QUERIES = [
    "보증금을 못 받고 있어요",
    "임차권등기명령은 어떻게 신청하나요",
    "집주인이 바뀌었는데 계약은 그대로인가요",
    "전세사기 피해자로 인정받으려면 뭐가 필요한가요",
    "임대인이 사망했어요",
]

UNRELATED_QUERIES = [
    "날씨 어때요",
    "오늘 점심 뭐 먹을까",
    "축구 경기 결과 알려줘",
    "파이썬 리스트 정렬하는 법",
    "가까운 카페 추천해줘",
]

retriever = DPartRetriever()


async def measure(query: str) -> list[float]:
    """질의 하나의 상위 TOP_K 거리를 반환한다(가까운 순)."""
    chunks = await retriever.search(query, top_k=TOP_K)
    return [c.distance for c in chunks if c.distance is not None]


async def run_group(label: str, queries: list[str]) -> list[float]:
    print(f"\n[{label}]")
    tops: list[float] = []
    for query in queries:
        distances = await measure(query)
        if not distances:
            print(f"  {query:<32} (검색 결과 없음)")
            continue
        tops.append(distances[0])
        rendered = "  ".join(f"{d:.3f}" for d in distances)
        verdict = "통과" if distances[0] < _MAX_DISTANCE else "차단"
        print(f"  {query:<32} {rendered}   -> {verdict}")
    return tops


async def main() -> None:
    print(f"임계값 _MAX_DISTANCE = {_MAX_DISTANCE}  (거리가 이보다 크면 무관으로 배제)")
    print(f"각 질의의 상위 {TOP_K}건 거리를 가까운 순으로 표시")

    related = await run_group("관련 질의", RELATED_QUERIES)
    unrelated = await run_group("무관 질의", UNRELATED_QUERIES)

    print("\n[요약]")
    if related:
        print(f"  관련 질의 최근접 거리   {min(related):.3f} ~ {max(related):.3f}")
    if unrelated:
        print(f"  무관 질의 최근접 거리   {min(unrelated):.3f} ~ {max(unrelated):.3f}")
    if related and unrelated:
        gap_low, gap_high = max(related), min(unrelated)
        if gap_low < gap_high:
            print(f"  두 분포 사이 빈 구간     {gap_low:.3f} ~ {gap_high:.3f}")
            inside = gap_low < _MAX_DISTANCE < gap_high
            print(f"  임계값 {_MAX_DISTANCE}는 이 구간 {'안에 있음' if inside else '밖에 있음 — 재검토 필요'}")
        else:
            print(f"  두 분포가 겹침({gap_high:.3f} ~ {gap_low:.3f}) — 거리만으로는 분리되지 않음")


if __name__ == "__main__":
    asyncio.run(main())
