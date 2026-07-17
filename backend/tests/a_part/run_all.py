from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.tests.a_part.run_conversation_state import main as run_conversation_state
from backend.tests.a_part.run_environment_db import run_environment_db
from backend.tests.a_part.run_evidence_gap15 import run_analysis
from backend.tests.a_part.run_multiturn import run_all as run_multiturn
from backend.tests.a_part.run_pdf_upload import main as run_pdf_upload
from backend.tests.a_part.run_search_answer20 import run_evaluation

EXPECTED_COLLECTIONS: dict[str, set[str]] = {
    "q01_owner_proxy": {"legal_sources", "safety_guarantee_sources"},
    "q02_co_owner": {"legal_sources", "document_analysis_sources"},
    "q03_owner_lessor_mismatch": {"legal_sources", "document_analysis_sources"},
    "q04_broker_account_payment": {"safety_guarantee_sources", "legal_sources"},
    "q05_account_change_before_contract": {"safety_guarantee_sources", "legal_sources"},
    "q06_broker_explanation_mismatch": {"document_analysis_sources", "legal_sources"},
    "q07_mortgage": {"legal_sources", "safety_guarantee_sources"},
    "q08_multiunit_priority": {"legal_sources", "safety_guarantee_sources"},
    "q09_registry_restriction_warning": {"legal_sources", "document_analysis_sources"},
    "q10_trust": {"legal_sources", "safety_guarantee_sources"},
    "q11_opposability_move_in": {"legal_sources", "procedure_sources"},
    "q12_fixed_date_priority": {"legal_sources", "procedure_sources"},
    "q13_owner_change": {"legal_sources", "procedure_sources"},
    "q14_special_clause_deposit_return": {"legal_sources", "document_analysis_sources"},
    "q15_after_contract_procedure": {"procedure_sources", "legal_sources"},
    "q16_lease_report": {"procedure_sources", "legal_sources"},
    "q17_household_certificate": {"procedure_sources", "legal_sources"},
    "q18_address_mismatch": {"document_analysis_sources", "legal_sources"},
    "q19_deposit_transfer_mismatch": {
        "document_analysis_sources",
        "safety_guarantee_sources",
        "legal_sources",
    },
    "q20_guarantee_check": {"safety_guarantee_sources", "procedure_sources"},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A파트 최종 챗봇 전체 검증")
    parser.add_argument("--downloads", type=Path, default=Path.home() / "Downloads")
    parser.add_argument("--json-output", type=Path)
    return parser.parse_args()


def validate_eval20(evaluation: dict[str, Any]) -> dict[str, int]:
    summary = evaluation.get("summary") or {}
    if summary != {"PASS": 20, "REVIEW": 0, "FAIL": 0, "ERROR": 0}:
        raise RuntimeError(f"답변 평가 20문항 실패: {summary}")

    collection_pass = 0
    direct_pass = 0
    search_errors = 0
    for item in evaluation.get("results") or []:
        response = item.get("response") or {}
        answer = response.get("answer") or {}
        references = answer.get("references") or []
        collections = {str(ref.get("collection")) for ref in references if ref.get("collection")}
        if collections & EXPECTED_COLLECTIONS[item["question_id"]]:
            collection_pass += 1
        if str(response.get("evidence_status") or "") == "sufficient" and references:
            direct_pass += 1
        if item.get("status") == "ERROR" or str(response.get("generation_status")) == "search_failed":
            search_errors += 1

    if (collection_pass, direct_pass, search_errors) != (20, 20, 0):
        raise RuntimeError(
            "검색 검증 실패: "
            f"collection={collection_pass}, direct={direct_pass}, errors={search_errors}"
        )

    print()
    print("유사도 검색")
    print("→ 질문 20개")
    print("→ 기대 collection 상위 포함 20개")
    print("→ 직접 근거 확인 20개")
    print("→ 검색 오류 0개")
    print()
    print("답변 평가")
    print("→ PASS 20")
    print("→ REVIEW 0")
    print("→ FAIL 0")
    print("→ ERROR 0")
    return {
        "question_count": 20,
        "collection_pass": collection_pass,
        "direct_pass": direct_pass,
        "search_errors": search_errors,
    }


def validate_gap(gap: dict[str, Any]) -> dict[str, int]:
    expected = {
        "BODY_DIRECT_IN_TOP30": 15,
        "BODY_DIRECT_OUTSIDE_TOP30": 0,
        "BODY_WEAK_ONLY": 0,
        "NO_BODY_EVIDENCE": 0,
        "ERROR": 0,
    }
    summary = gap.get("summary") or {}
    if summary != expected:
        raise RuntimeError(f"근거 갭 결과 불일치: {summary}")
    print()
    print("근거 갭")
    print("→ BODY_DIRECT_IN_TOP30 15")
    print("→ 나머지 상태 0")
    return summary


def run_pdf_documents(downloads: Path) -> None:
    script = PROJECT_ROOT / "backend/tests/a_part/run_pdf_documents.py"
    completed = subprocess.run(
        [sys.executable, "-B", str(script), "--downloads", str(downloads)],
        cwd=PROJECT_ROOT,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"PDF 문서 최종 테스트 실패: exit={completed.returncode}")


def main() -> None:
    args = parse_args()
    downloads = args.downloads.expanduser().resolve()
    result: dict[str, Any] = {}

    try:
        result["environment_db"] = run_environment_db()

        print()
        print("=" * 116)
        print("유사도 검색·답변 평가 20문항")
        print("=" * 116)
        result["evaluation20"] = validate_eval20(run_evaluation(full=False))

        print()
        print("=" * 116)
        print("근거 갭 15문항")
        print("=" * 116)
        result["evidence_gap"] = validate_gap(run_analysis())

        print()
        print("=" * 116)
        print("대화 상태")
        print("=" * 116)
        run_conversation_state()
        result["conversation_state"] = "PASS"

        print()
        print("=" * 116)
        print("PDF 파일 업로드")
        print("=" * 116)
        run_pdf_upload()
        result["pdf_upload"] = "PASS"

        print()
        print("=" * 116)
        print("PDF 업로드·OCR·분석·비교·실제 상담")
        print("=" * 116)
        run_pdf_documents(downloads)
        result["pdf_documents"] = "PASS"

        print()
        print("=" * 116)
        print("실제 서비스형 다중 멀티턴 상담")
        print("=" * 116)
        multiturn = run_multiturn(downloads)
        result["multiturn"] = multiturn
        if multiturn.get("final") != "PASS":
            raise RuntimeError(f"다중 멀티턴 실패: {multiturn.get('total')}")

        result["final"] = "PASS"
    except Exception as exc:
        result["final"] = "FAIL"
        result["error"] = repr(exc)
        if args.json_output:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(
                json.dumps(result, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        print()
        print("=" * 116)
        print("A파트 최종 챗봇 검증")
        print("-" * 116)
        print("최종 판정 → FAIL")
        print("오류:", repr(exc))
        raise

    print()
    print("=" * 116)
    print("A파트 최종 챗봇 검증")
    print("-" * 116)
    print("환경·DB → PASS")
    print("유사도 검색·답변 평가 20문항 → PASS")
    print("근거 갭 15문항 → PASS")
    print("대화 상태 → PASS")
    print("PDF 파일 업로드 → PASS")
    print("PDF 문서 4개 OCR·분석·비교·상담 → PASS")
    print("자연어 20문항 × 5턴 → PASS")
    print("PDF 2문항 × 4턴 → PASS")
    print("최종 판정 → PASS")

    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print("JSON 결과 저장:", args.json_output)


if __name__ == "__main__":
    main()
