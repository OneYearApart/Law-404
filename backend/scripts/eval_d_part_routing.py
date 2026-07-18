"""
D파트 라우팅 골든셋 평가.

골든셋(docs/d_part/eval/routing_golden.jsonl)은 supervisor가 판별해야 할 상황모델 축
(recognized / risk_signals / topic / special_case)과 그로부터 파생되는 최종 경로를 라벨로 갖는다.
라벨은 _normalize_overlap_axes 정규화를 거친 '뒤'의 값이다 — 정규화와 route()는
결정론적 코드라 평가 대상이 아니라 채점 함수의 일부이기 때문이다.

두 가지 모드:

  --validate : API 호출 없이 라벨의 자기무결성만 검사한다. 라벨의 축 값에서 route()를
               돌린 결과가 라벨의 route와 일치하는지, topic/special_case 문자열이 실제
               스키마 어휘인지 확인한다. 골든셋을 고칠 때마다 먼저 이걸 돌린다.

  --run      : 실제로 call_supervisor를 호출해 정확도를 측정한다(과금). LANGSMITH_TRACING=true면
               모든 호출이 LangSmith에 남아 케이스별 프롬프트/토큰/지연을 그대로 열어볼 수 있다.

사용:
    python -X utf8 scripts/eval_d_part_routing.py --validate
    python -X utf8 scripts/eval_d_part_routing.py --run
    python -X utf8 scripts/eval_d_part_routing.py --run --only hrd,neg
"""
import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

# LangSmith SDK는 os.environ을 직접 읽는데, config.py의 pydantic-settings는 .env를 Settings
# 객체로만 읽고 os.environ에는 올리지 않는다(실측 확인). 서버는 기동 시 a/c파트 모듈의
# load_dotenv()가 우연히 환경변수를 채워주지만, 이 스크립트는 d파트만 임포트하므로 그 우연이
# 없다 — 명시적으로 안 부르면 LANGSMITH_*가 .env에 있어도 트레이싱이 조용히 꺼진 채로 돈다.
# config.py와 같은 두 위치를 같은 순서로 본다. 이미 있는 환경변수는 덮어쓰지 않는다(dotenv 기본값).
from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_ROOT / ".env")
load_dotenv(BACKEND_ROOT.parent / ".env")

from app.graph.parts.d_part.nodes.supervisor import (  # noqa: E402
    route,
    situation_from_supervisor_result,
)
from app.graph.parts.d_part.schemas import (
    GENERAL_TOPIC_LABELS,
    RISK_SIGNALS,
    SPECIAL_CASE_CATEGORIES,
)

GOLDEN_PATH = BACKEND_ROOT / "docs" / "d_part" / "eval" / "routing_golden.jsonl"
RESULTS_DIR = BACKEND_ROOT / "docs" / "d_part" / "eval" / "results"

MAX_CONCURRENCY = 5  # supervisor는 턴당 1회 호출이라 가벼우나 RateLimitError 재시도를 피하려 조인다


def load_golden() -> list[dict]:
    """골든셋 JSONL을 읽는다. '_comment' 키만 있는 줄은 파일 내 주석이라 건너뛴다."""
    cases = []
    for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if "_comment" in record:
            continue
        cases.append(record)
    return cases


def _situation_of(case: dict):
    """라벨의 축 값을 상황모델로 되돌린다. 라벨이 이미 정규화 후 값이라 정규화는 멱등이다."""
    return situation_from_supervisor_result(
        {
            "recognized": case["recognized"],
            "risk_signals": case["risk_signals"],
            "topic": case["topic"],
            "special_case": case["special_case"],
        }
    )


def validate(cases: list[dict]) -> int:
    """라벨의 자기무결성 검사. 반환값은 발견된 오류 수(그대로 종료코드로 쓴다)."""
    errors: list[str] = []
    seen_ids: set[str] = set()

    for case in cases:
        cid = case.get("id", "<id 없음>")
        if cid in seen_ids:
            errors.append(f"{cid}: id 중복")
        seen_ids.add(cid)

        for field in ("utterance", "recognized", "risk_signals", "topic", "special_case", "route", "note"):
            if field not in case:
                errors.append(f"{cid}: 필드 '{field}' 누락")
        if len(case) != 7:  # 위 7개 외 오타 필드가 섞이면 조용히 무시되므로 막는다
            extra = set(case) - {"utterance", "recognized", "risk_signals", "topic", "special_case", "route", "note", "id"}
            if extra:
                errors.append(f"{cid}: 알 수 없는 필드 {sorted(extra)}")

        # 어휘 검사 — SituationState의 validator가 조용히 None으로 만들어버리기 전에 잡는다
        if case.get("topic") is not None and case["topic"] not in GENERAL_TOPIC_LABELS:
            errors.append(f"{cid}: topic '{case['topic']}'은 GENERAL_TOPIC_LABELS에 없음")
        if case.get("special_case") is not None and case["special_case"] not in SPECIAL_CASE_CATEGORIES:
            errors.append(f"{cid}: special_case '{case['special_case']}'는 SPECIAL_CASE_CATEGORIES에 없음")
        for signal in case.get("risk_signals") or []:
            if signal not in RISK_SIGNALS:
                errors.append(f"{cid}: risk_signal '{signal}'은 RISK_SIGNALS에 없음")

        # 핵심 검사 — 라벨한 축에서 route()를 돌리면 라벨한 경로가 나와야 한다
        derived = route(_situation_of(case))
        if derived != case.get("route"):
            errors.append(f"{cid}: route 라벨이 '{case.get('route')}'인데 축에서 파생되는 값은 '{derived}'")

    for error in errors:
        print(f"  ✗ {error}")
    print(f"\n{len(cases)}개 케이스 검사 — 오류 {len(errors)}건")
    if not errors:
        print("라벨 자기무결성 OK. --run으로 실측할 수 있습니다.")
    return len(errors)


async def _predict(case: dict, semaphore: asyncio.Semaphore) -> dict:
    """supervisor를 실제로 호출해 예측 축과 경로를 얻는다."""
    from app.llm.d_part import call_supervisor

    async with semaphore:
        started = time.perf_counter()
        try:
            raw = await call_supervisor(case["utterance"])
            error = None
        except Exception as exc:  # 케이스 하나가 죽어도 나머지 측정은 계속한다
            raw, error = {}, f"{type(exc).__name__}: {exc}"
        elapsed = time.perf_counter() - started

    situation = situation_from_supervisor_result(raw) if error is None else None
    return {
        "id": case["id"],
        "utterance": case["utterance"],
        "error": error,
        "latency_s": round(elapsed, 3),
        "expected": {k: case[k] for k in ("recognized", "risk_signals", "topic", "special_case", "route")},
        "predicted": None
        if situation is None
        else {
            "recognized": situation.recognized,
            "risk_signals": list(situation.risk_signals),
            "topic": situation.topic,
            "special_case": situation.special_case,
            "route": route(situation),
        },
        "note": case["note"],
    }


def _score(results: list[dict]) -> dict:
    """경로 정확도를 주지표로, 축별 지표를 보조로 낸다.

    risk_signals는 다중 라벨이라 정확도 대신 마이크로 P/R/F1을 쓴다 — 대부분의 케이스가 빈
    배열이므로 정확도로 재면 '아무것도 검출 안 함'이 고득점을 받는다.
    """
    scored = [r for r in results if r["predicted"] is not None]
    total = len(scored)
    if total == 0:
        return {"error": "채점 가능한 결과 없음"}

    route_hits = sum(r["expected"]["route"] == r["predicted"]["route"] for r in scored)
    recognized_hits = sum(r["expected"]["recognized"] == r["predicted"]["recognized"] for r in scored)
    topic_hits = sum(r["expected"]["topic"] == r["predicted"]["topic"] for r in scored)

    # special_case는 인지형에서만 채점한다. 미인지형에선 route()가 이 축을 읽지 않고(recognized
    # 블록 안에서만 읽힌다) 모델이 채울지도 비결정적이라, 전체를 채점하면 행동에 아무 영향이 없는
    # 차이에 감점이 붙어 지표가 노이즈를 잰다.
    special_scored = [r for r in scored if r["expected"]["recognized"]]
    special_hits = sum(r["expected"]["special_case"] == r["predicted"]["special_case"] for r in special_scored)

    tp = fp = fn = 0
    for r in scored:
        expected = set(r["expected"]["risk_signals"])
        predicted = set(r["predicted"]["risk_signals"])
        tp += len(expected & predicted)
        fp += len(predicted - expected)
        fn += len(expected - predicted)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    confusion = Counter(
        (r["expected"]["route"], r["predicted"]["route"]) for r in scored if r["expected"]["route"] != r["predicted"]["route"]
    )
    latencies = sorted(r["latency_s"] for r in scored)

    return {
        "n": total,
        "n_errored": len(results) - total,
        "route_accuracy": round(route_hits / total, 4),
        "recognized_accuracy": round(recognized_hits / total, 4),
        "topic_exact_match": round(topic_hits / total, 4),
        "special_case_exact_match_recognized_only": round(special_hits / len(special_scored), 4)
        if special_scored
        else None,
        "special_case_n_scored": len(special_scored),
        "risk_signals_micro": {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        },
        "latency_s": {
            "p50": latencies[len(latencies) // 2],
            "p95": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
        },
        "route_confusion": {f"{exp} → {pred}": n for (exp, pred), n in confusion.most_common()},
    }


def _tracing_status() -> str:
    """트레이싱이 실제로 켜졌는지 실행 전에 드러낸다.

    꺼진 줄 모르고 베이스라인을 돌리면 비교 대상 트레이스가 통째로 없어서 측정을 다시 해야 한다.
    LangSmith SDK가 실제로 보는 값(os.environ)을 그대로 확인한다 — .env에 썼는지가 아니라.
    """
    import os

    enabled = os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
    has_key = bool(os.environ.get("LANGSMITH_API_KEY"))
    project = os.environ.get("LANGSMITH_PROJECT") or "(기본값: default)"

    if enabled and has_key:
        return f"✅ LangSmith 트레이싱 ON — 프로젝트 '{project}'"
    if enabled and not has_key:
        return "⚠️  LANGSMITH_TRACING=true인데 LANGSMITH_API_KEY가 없음 — 트레이스가 전송되지 않습니다"
    return "⚠️  LangSmith 트레이싱 OFF — 지표는 나오지만 트레이스는 안 남습니다"


async def run(cases: list[dict]) -> None:
    print(_tracing_status())
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    started = time.perf_counter()
    results = await asyncio.gather(*(_predict(case, semaphore) for case in cases))
    wall = time.perf_counter() - started

    metrics = _score(results)

    print(f"\n{'=' * 70}")
    print(f"D파트 라우팅 평가 — {metrics['n']}건 채점 (실패 {metrics['n_errored']}건), 총 {wall:.1f}초")
    print(f"{'=' * 70}")
    print(f"  경로 정확도            {metrics['route_accuracy']:.1%}   ← 주지표")
    print(f"  recognized 정확도      {metrics['recognized_accuracy']:.1%}")
    print(f"  topic 정확일치         {metrics['topic_exact_match']:.1%}")
    print(f"  special_case 정확일치  {metrics['special_case_exact_match_recognized_only']:.1%}  (인지형 {metrics['special_case_n_scored']}건만)")
    rs = metrics["risk_signals_micro"]
    print(f"  risk_signals micro-F1  {rs['f1']:.3f}  (P {rs['precision']:.3f} / R {rs['recall']:.3f}, TP{rs['tp']} FP{rs['fp']} FN{rs['fn']})")
    print(f"  지연 p50/p95           {metrics['latency_s']['p50']:.2f}s / {metrics['latency_s']['p95']:.2f}s")

    if metrics["route_confusion"]:
        print("\n  경로 오분류:")
        for pair, n in metrics["route_confusion"].items():
            print(f"    {pair}  ×{n}")

    misses = [r for r in results if r["predicted"] and r["expected"]["route"] != r["predicted"]["route"]]
    if misses:
        print(f"\n  틀린 케이스 {len(misses)}건:")
        for r in misses:
            print(f"    [{r['id']}] {r['utterance']}")
            print(f"       기대 {r['expected']['route']} / 실제 {r['predicted']['route']}")
            print(f"       기대축 {r['expected']} \n       실제축 {r['predicted']}")

    errored = [r for r in results if r["error"]]
    if errored:
        print(f"\n  호출 실패 {len(errored)}건:")
        for r in errored:
            print(f"    [{r['id']}] {r['error']}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = RESULTS_DIR / f"routing-{stamp}.json"
    out_path.write_text(
        json.dumps({"metrics": metrics, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n결과 저장: {out_path.relative_to(BACKEND_ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="D파트 라우팅 골든셋 평가")
    parser.add_argument("--validate", action="store_true", help="API 호출 없이 라벨 무결성만 검사")
    parser.add_argument("--run", action="store_true", help="supervisor를 실제 호출해 정확도 측정(과금)")
    parser.add_argument("--only", help="id 접두어 쉼표 목록으로 케이스를 거른다 (예: hrd,neg)")
    args = parser.parse_args()

    if not (args.validate or args.run):
        parser.error("--validate 또는 --run 중 하나는 필요합니다")

    cases = load_golden()
    if args.only:
        prefixes = tuple(p.strip() for p in args.only.split(","))
        cases = [c for c in cases if c["id"].startswith(prefixes)]
        print(f"필터 '{args.only}' 적용 — {len(cases)}건")

    if args.validate:
        return 1 if validate(cases) else 0

    asyncio.run(run(cases))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
