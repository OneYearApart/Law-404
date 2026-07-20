"""
D파트 전세사기 피해자 판정(victim_check) 골든셋 평가.

라우팅 골든셋이 "문 앞까지 제대로 도착하는가"를 잰다면 이건 "문 안에서 제대로 판정하는가"를 잰다.
D파트에서 가장 위험한 출력이다 — 사람에게 전세사기피해자법 요건 충족 가능성을 말하는 경로다.

**LLM이 하는 일은 슬롯 추출 하나뿐이다.** 병합(_merge_slots), 다음질문 선택
(_unresolved_required_slots), 최종판정(_compute_judgment), fallback/제외 게이트는 전부
결정론적 코드다. 그래서 라벨은 각 턴이 끝난 시점의 **병합된 슬롯 상태**로 달고, 결정론 코드는
평가 대상이 아니라 채점 함수의 일부로 쓴다(라우팅 골든셋과 같은 원리).

턴 간에는 DPartSessionState가 실제로 넘기는 필드만 이어받는다 — 전체 state를 그대로 넘기면
final_answer가 남아 노드가 조기 return하고, 실제 대화와 다른 것을 측정하게 된다.

두 가지 모드:
  --validate : API 없이 라벨의 자기무결성 검사(라벨 슬롯에서 다음질문·최종판정이 실제로 파생되는지)
  --run      : 실제 대화를 턴 단위로 재생해 정확도 측정(과금)

사용:
    python -X utf8 scripts/eval_d_part_victim.py --validate
    python -X utf8 scripts/eval_d_part_victim.py --run
    python -X utf8 scripts/eval_d_part_victim.py --run --only vj-002
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

# LangSmith SDK는 os.environ을 직접 읽는데 pydantic-settings는 .env를 거기 올리지 않는다.
# 자세한 사정은 eval_d_part_routing.py의 같은 위치 주석 참조.
from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_ROOT / ".env")
load_dotenv(BACKEND_ROOT.parent / ".env")

from app.graph.parts.d_part.nodes.victim_check import (  # noqa: E402
    _EXCLUSION_MESSAGE,
    _SLOT_ORDER,
    _compute_judgment,
    _unresolved_required_slots,
    check_victim_status,
)
from app.graph.parts.d_part.schemas import SlotStatus, VictimRequirementSlots  # noqa: E402

GOLDEN_PATH = BACKEND_ROOT / "docs" / "d_part" / "eval" / "victim_golden.json"
RESULTS_DIR = BACKEND_ROOT / "docs" / "d_part" / "eval" / "results"

# DPartSessionState가 실제로 턴 간에 넘기는 필드(turn_history는 복원 전용이라 그래프에 안 들어간다).
CARRYOVER_FIELDS = (
    "persona",
    "situation",
    "victim_slots",
    "victim_judgment",
    "victim_fallback",
    "victim_flow_closed",
    "victim_check_attempts",
    "victim_pending_slot",
    "awaiting_relief_confirmation",
)


def load_golden() -> list[dict]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def _slots_from_label(label: dict) -> VictimRequirementSlots:
    return VictimRequirementSlots(
        moved_in_and_fixed_date=SlotStatus(label["moved_in_and_fixed_date"]),
        deposit_under_limit=SlotStatus(label["deposit_under_limit"]),
        multiple_victims=SlotStatus(label["multiple_victims"]),
        no_intent_to_return=SlotStatus(label["no_intent_to_return"]),
        auction_completed=label["auction_completed"],
    )


def validate(scenarios: list[dict]) -> int:
    """라벨 슬롯에서 다음질문·최종판정이 실제로 파생되는지 검사한다(API 호출 없음)."""
    errors: list[str] = []
    valid_asks = set(_SLOT_ORDER) | {"relief", None}

    for scenario in scenarios:
        sid = scenario["id"]
        outcome = scenario["expect_outcome"]
        if outcome not in ("judgment", "exclusion", "fallback"):
            errors.append(f"{sid}: 알 수 없는 expect_outcome '{outcome}'")

        for index, turn in enumerate(scenario["turns"]):
            where = f"{sid} turn{index + 1}"
            ask = turn["expect_ask"]
            if ask not in valid_asks:
                errors.append(f"{where}: 알 수 없는 expect_ask '{ask}'")
                continue

            slots = _slots_from_label(turn["slots"])
            unresolved = _unresolved_required_slots(slots)
            is_last = index == len(scenario["turns"]) - 1

            if ask in _SLOT_ORDER:
                if not unresolved:
                    errors.append(f"{where}: expect_ask가 '{ask}'인데 미해결 슬롯이 없음")
                elif unresolved[0] != ask:
                    errors.append(
                        f"{where}: expect_ask가 '{ask}'인데 라벨 슬롯에서 파생되는 다음 질문은 '{unresolved[0]}'"
                    )
            elif ask == "relief":
                if unresolved:
                    errors.append(f"{where}: expect_ask가 'relief'인데 미해결 슬롯이 남아있음 {unresolved}")
            elif ask is None:
                if not is_last:
                    errors.append(f"{where}: 마지막 턴이 아닌데 expect_ask가 null")
                # fallback은 미해결 슬롯을 남긴 채 종결하는 게 정상이라 검사에서 뺀다
                elif unresolved and outcome != "fallback":
                    errors.append(f"{where}: 종결 턴인데 미해결 슬롯이 남아있음 {unresolved}")

        # 최종 판정은 마지막 턴의 라벨 슬롯에서 규칙으로 파생돼야 한다
        final_slots = _slots_from_label(scenario["turns"][-1]["slots"])
        expected_judgment = scenario["expect_judgment"]
        if outcome == "judgment":
            derived = _compute_judgment(final_slots).value
            if derived != expected_judgment:
                errors.append(
                    f"{sid}: expect_judgment가 '{expected_judgment}'인데 최종 슬롯에서 파생되는 값은 '{derived}'"
                )
        elif expected_judgment is not None:
            errors.append(f"{sid}: outcome '{outcome}'인데 expect_judgment가 null이 아님")

    for error in errors:
        print(f"  ✗ {error}")
    turns = sum(len(s["turns"]) for s in scenarios)
    print(f"\n시나리오 {len(scenarios)}개 / 턴 {turns}개 검사 — 오류 {len(errors)}건")
    if not errors:
        print("라벨 자기무결성 OK. --run으로 실측할 수 있습니다.")
    return len(errors)


def _observed_ask(state: dict) -> str | None:
    if state.get("awaiting_relief_confirmation"):
        return "relief"
    return state.get("victim_pending_slot")


def _observed_outcome(state: dict) -> str | None:
    if state.get("victim_fallback"):
        return "fallback"
    if state.get("final_answer") == _EXCLUSION_MESSAGE:
        return "exclusion"
    if state.get("victim_judgment") is not None:
        return "judgment"
    return None


async def _replay(scenario: dict) -> dict:
    """시나리오 한 편을 턴 단위로 재생한다. 턴 간에는 carryover 필드만 넘긴다."""
    carry: dict = {}
    turn_results = []

    for index, turn in enumerate(scenario["turns"]):
        state = dict(carry)
        state["user_input"] = turn["user"]
        started = time.perf_counter()
        try:
            state = await check_victim_status(state)
            error = None
        except Exception as exc:  # 한 턴이 죽어도 나머지 시나리오 결과는 남긴다
            error = f"{type(exc).__name__}: {exc}"
        elapsed = time.perf_counter() - started

        if error is not None:
            turn_results.append({"index": index + 1, "user": turn["user"], "error": error})
            break

        slots = state.get("victim_slots") or VictimRequirementSlots()
        predicted = {name: getattr(slots, name).value if getattr(slots, name) else None for name in _SLOT_ORDER}
        predicted["auction_completed"] = slots.auction_completed

        turn_results.append(
            {
                "index": index + 1,
                "user": turn["user"],
                "error": None,
                "latency_s": round(elapsed, 3),
                "expected_slots": turn["slots"],
                "predicted_slots": predicted,
                "expected_ask": turn["expect_ask"],
                "predicted_ask": _observed_ask(state),
                "note": turn["note"],
            }
        )

        carry = {k: state[k] for k in CARRYOVER_FIELDS if k in state}

    judgment = state.get("victim_judgment") if turn_results and turn_results[-1].get("error") is None else None
    return {
        "id": scenario["id"],
        "title": scenario["title"],
        "turns": turn_results,
        "expected_outcome": scenario["expect_outcome"],
        "predicted_outcome": _observed_outcome(state) if turn_results[-1].get("error") is None else None,
        "expected_judgment": scenario["expect_judgment"],
        "predicted_judgment": judgment.value if judgment is not None else None,
    }


def _score(results: list[dict]) -> dict:
    slot_total = slot_hits = 0
    auction_total = auction_hits = 0
    ask_total = ask_hits = 0
    confusion: Counter = Counter()
    latencies: list[float] = []

    for scenario in results:
        for turn in scenario["turns"]:
            if turn.get("error") is not None:
                continue
            latencies.append(turn["latency_s"])
            for name in _SLOT_ORDER:
                expected, predicted = turn["expected_slots"][name], turn["predicted_slots"][name]
                slot_total += 1
                if expected == predicted:
                    slot_hits += 1
                else:
                    confusion[(expected, predicted)] += 1
            auction_total += 1
            if turn["expected_slots"]["auction_completed"] == turn["predicted_slots"]["auction_completed"]:
                auction_hits += 1
            ask_total += 1
            if turn["expected_ask"] == turn["predicted_ask"]:
                ask_hits += 1

    outcome_hits = sum(s["expected_outcome"] == s["predicted_outcome"] for s in results)
    judgment_hits = sum(s["expected_judgment"] == s["predicted_judgment"] for s in results)

    # 안전 지표: 실제로는 구제수단이 없는데 '제외'로 끝난 시나리오. 진짜 피해자를 지원대상에서
    # 부당하게 떨어뜨리는 사고라 정확도와 별개로 따로 센다 — 0이 아니면 다른 수치가 좋아도 실패다.
    wrongful_exclusions = [
        s["id"] for s in results if s["predicted_outcome"] == "exclusion" and s["expected_outcome"] != "exclusion"
    ]
    latencies.sort()

    return {
        "n_scenarios": len(results),
        "n_turns": ask_total,
        "slot_accuracy": round(slot_hits / slot_total, 4) if slot_total else None,
        "auction_accuracy": round(auction_hits / auction_total, 4) if auction_total else None,
        "next_question_accuracy": round(ask_hits / ask_total, 4) if ask_total else None,
        "outcome_accuracy": round(outcome_hits / len(results), 4) if results else None,
        "judgment_accuracy": round(judgment_hits / len(results), 4) if results else None,
        "wrongful_exclusions": wrongful_exclusions,
        "slot_confusion": {f"{exp} → {pred}": n for (exp, pred), n in confusion.most_common()},
        "latency_s": {
            "p50": latencies[len(latencies) // 2],
            "p95": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
        }
        if latencies
        else None,
    }


def _tracing_status() -> str:
    import os

    enabled = os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
    has_key = bool(os.environ.get("LANGSMITH_API_KEY"))
    project = os.environ.get("LANGSMITH_PROJECT") or "(기본값: default)"
    if enabled and has_key:
        return f"✅ LangSmith 트레이싱 ON — 프로젝트 '{project}'"
    if enabled and not has_key:
        return "⚠️  LANGSMITH_TRACING=true인데 LANGSMITH_API_KEY가 없음 — 트레이스가 전송되지 않습니다"
    return "⚠️  LangSmith 트레이싱 OFF — 지표는 나오지만 트레이스는 안 남습니다"


async def run(scenarios: list[dict]) -> None:
    print(_tracing_status())
    started = time.perf_counter()
    # 시나리오 내부는 턴이 순차 의존이라 병렬화할 수 없다. 시나리오끼리만 병렬로 돌린다.
    results = await asyncio.gather(*(_replay(s) for s in scenarios))
    wall = time.perf_counter() - started

    metrics = _score(results)

    print(f"\n{'=' * 70}")
    print(f"D파트 피해자 판정 평가 — 시나리오 {metrics['n_scenarios']}개 / 턴 {metrics['n_turns']}개, 총 {wall:.1f}초")
    print(f"{'=' * 70}")
    print(f"  최종 판정 정확도       {metrics['judgment_accuracy']:.1%}   ← 주지표")
    print(f"  종결 형태 정확도       {metrics['outcome_accuracy']:.1%}   (판정/제외/폴백)")
    print(f"  슬롯 정확도            {metrics['slot_accuracy']:.1%}   (4슬롯 × {metrics['n_turns']}턴)")
    print(f"  다음질문 정확도        {metrics['next_question_accuracy']:.1%}")
    print(f"  auction_completed      {metrics['auction_accuracy']:.1%}")
    print(f"  지연 p50/p95           {metrics['latency_s']['p50']:.2f}s / {metrics['latency_s']['p95']:.2f}s")

    if metrics["wrongful_exclusions"]:
        print(f"\n  🔴 부당 제외 {len(metrics['wrongful_exclusions'])}건: {metrics['wrongful_exclusions']}")
    else:
        print("\n  ✅ 부당 제외 0건")

    if metrics["slot_confusion"]:
        print("\n  슬롯 오분류:")
        for pair, n in metrics["slot_confusion"].items():
            print(f"    {pair}  ×{n}")

    for scenario in results:
        bad_turns = [
            t
            for t in scenario["turns"]
            if t.get("error") is not None
            or t["expected_slots"] != t["predicted_slots"]
            or t["expected_ask"] != t["predicted_ask"]
        ]
        judgment_ok = scenario["expected_judgment"] == scenario["predicted_judgment"]
        outcome_ok = scenario["expected_outcome"] == scenario["predicted_outcome"]
        if not bad_turns and judgment_ok and outcome_ok:
            continue
        print(f"\n  [{scenario['id']}] {scenario['title']}")
        if not outcome_ok or not judgment_ok:
            print(
                f"    종결: 기대 {scenario['expected_outcome']}/{scenario['expected_judgment']}"
                f" → 실제 {scenario['predicted_outcome']}/{scenario['predicted_judgment']}"
            )
        for turn in bad_turns:
            if turn.get("error") is not None:
                print(f"    turn{turn['index']} \"{turn['user']}\" → 실패 {turn['error']}")
                continue
            print(f"    turn{turn['index']} \"{turn['user']}\"")
            for name in (*_SLOT_ORDER, "auction_completed"):
                expected, predicted = turn["expected_slots"][name], turn["predicted_slots"][name]
                if expected != predicted:
                    print(f"       {name}: 기대 {expected} / 실제 {predicted}")
            if turn["expected_ask"] != turn["predicted_ask"]:
                print(f"       다음질문: 기대 {turn['expected_ask']} / 실제 {turn['predicted_ask']}")
            print(f"       ↳ {turn['note']}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = RESULTS_DIR / f"victim-{stamp}.json"
    out_path.write_text(
        json.dumps({"metrics": metrics, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n결과 저장: {out_path.relative_to(BACKEND_ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="D파트 피해자 판정 골든셋 평가")
    parser.add_argument("--validate", action="store_true", help="API 호출 없이 라벨 무결성만 검사")
    parser.add_argument("--run", action="store_true", help="실제 대화를 재생해 정확도 측정(과금)")
    parser.add_argument("--only", help="시나리오 id 쉼표 목록 (예: vj-002,vj-005)")
    args = parser.parse_args()

    if not (args.validate or args.run):
        parser.error("--validate 또는 --run 중 하나는 필요합니다")

    scenarios = load_golden()
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        scenarios = [s for s in scenarios if s["id"] in wanted]
        print(f"필터 적용 — 시나리오 {len(scenarios)}개")

    if args.validate:
        return 1 if validate(scenarios) else 0

    asyncio.run(run(scenarios))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
