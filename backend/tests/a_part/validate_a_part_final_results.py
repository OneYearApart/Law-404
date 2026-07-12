# backend/tests/a_part/validate_a_part_final_results.py
# 정리된 A파트 코드·데이터·DB·20문항 평가·근거 갭 결과가 최종 기준을 충족하는지 검증한다.

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import psycopg2
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
TEST_ROOT = PROJECT_ROOT / "backend/tests/a_part"
ENV_PATH = PROJECT_ROOT / "backend/.env"

EXPECTED_ANSWER_VERSION = "answer-v16-final-service-evidence"
EXPECTED_SEARCH_VERSION = "routing-rerank-v10-final-service-evidence"
EXPECTED_EVAL_SUMMARY = {
    "PASS": 20,
    "REVIEW": 0,
    "FAIL": 0,
    "ERROR": 0,
}
EXPECTED_GAP_SUMMARY = {
    "BODY_DIRECT_IN_TOP30": 15,
    "BODY_DIRECT_OUTSIDE_TOP30": 0,
    "BODY_WEAK_ONLY": 0,
    "NO_BODY_EVIDENCE": 0,
    "ERROR": 0,
}
EXPECTED_TOP_LEVEL_FILES = {
    "README.md",
    "analyze_a_part_evidence_gaps.py",
    "commit_a_part_final.sh",
    "ensure_a_part_service_evidence.py",
    "run_a_part_answer_eval20.py",
    "run_a_part_final_validation.sh",
    "validate_a_part_final_results.py",
}
SERVICE_CARDS = [
    (
        "safety_guarantee_sources",
        "law404_payment_recipient_authority_rule_c0001",
        PROJECT_ROOT
        / "backend/data/a_part/rag/safety_guarantee_source_chunks.jsonl",
    ),
    (
        "document_analysis_sources",
        "law404_special_clause_return_rule_c0001",
        PROJECT_ROOT
        / "backend/data/a_part/rag/document_analysis_source_chunks.jsonl",
    ),
    (
        "procedure_sources",
        "law404_household_certificate_timing_rule_c0001",
        PROJECT_ROOT
        / "backend/data/a_part/rag/procedure_source_chunks.jsonl",
    ),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=PROJECT_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def load_json(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"결과 파일이 없습니다: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl_card(path: Path, document_id: str) -> dict:
    matches: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("chunk_id") == document_id:
            matches.append(row)
    if len(matches) != 1:
        raise RuntimeError(
            f"{path}: {document_id} 카드 수가 1개가 아닙니다: {len(matches)}"
        )
    return matches[0]


def validate_file_layout(errors: list[str]) -> list[str]:
    actual_files = {
        path.name
        for path in TEST_ROOT.iterdir()
        if path.is_file() and not path.name.startswith(".")
    }
    extras = sorted(actual_files - EXPECTED_TOP_LEVEL_FILES)
    missing = sorted(EXPECTED_TOP_LEVEL_FILES - actual_files)
    if extras:
        errors.append(f"A파트 테스트 폴더에 불필요한 파일이 남았습니다: {extras}")
    if missing:
        errors.append(f"A파트 최종 필수 파일이 없습니다: {missing}")
    cache_dirs = [str(path.relative_to(TEST_ROOT)) for path in TEST_ROOT.rglob("__pycache__")]
    pyc_files = [str(path.relative_to(TEST_ROOT)) for path in TEST_ROOT.rglob("*.pyc")]
    if cache_dirs or pyc_files:
        errors.append(
            f"파이썬 캐시가 남았습니다: dirs={cache_dirs}, files={pyc_files}"
        )
    return sorted(actual_files)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", required=True)
    parser.add_argument("--gap", required=True)
    parser.add_argument("--gap-csv", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    eval_path = Path(args.eval)
    gap_path = Path(args.gap)
    gap_csv_path = Path(args.gap_csv)
    output_path = Path(args.output)
    errors: list[str] = []

    from backend.app.llm.a_part import ANSWER_CODE_VERSION
    from backend.app.rag.retrievers.a_part import CODE_VERSION

    if ANSWER_CODE_VERSION != EXPECTED_ANSWER_VERSION:
        errors.append(
            f"답변 코드 버전 불일치: {ANSWER_CODE_VERSION}"
        )
    if CODE_VERSION != EXPECTED_SEARCH_VERSION:
        errors.append(f"검색 코드 버전 불일치: {CODE_VERSION}")

    evaluation = load_json(eval_path)
    gap = load_json(gap_path)

    if evaluation.get("summary") != EXPECTED_EVAL_SUMMARY:
        errors.append(
            f"20문항 평가 요약 불일치: {evaluation.get('summary')}"
        )
    eval_results = evaluation.get("results") or []
    eval_ids = [item.get("question_id") for item in eval_results]
    if len(eval_results) != 20 or len(set(eval_ids)) != 20:
        errors.append(
            f"평가 문항 수 또는 ID 중복 오류: count={len(eval_results)}"
        )
    non_pass = [
        item.get("question_id")
        for item in eval_results
        if item.get("status") != "PASS"
    ]
    if non_pass:
        errors.append(f"PASS가 아닌 평가 문항: {non_pass}")

    if gap.get("summary") != EXPECTED_GAP_SUMMARY:
        errors.append(f"근거 갭 요약 불일치: {gap.get('summary')}")
    gap_results = gap.get("results") or []
    non_direct = [
        item.get("question_id")
        for item in gap_results
        if item.get("classification") != "BODY_DIRECT_IN_TOP30"
    ]
    if len(gap_results) != 15 or non_direct:
        errors.append(
            f"근거 갭 최종 상태 오류: count={len(gap_results)}, "
            f"non_direct={non_direct}"
        )

    if not gap_csv_path.exists():
        errors.append(f"근거 갭 CSV가 없습니다: {gap_csv_path}")
        gap_csv_rows = 0
    else:
        with gap_csv_path.open(encoding="utf-8-sig", newline="") as file:
            gap_csv_rows = sum(1 for _ in csv.reader(file)) - 1
        if gap_csv_rows != 15:
            errors.append(f"근거 갭 CSV 행 수가 15가 아닙니다: {gap_csv_rows}")

    final_files = validate_file_layout(errors)

    load_dotenv(ENV_PATH)
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://edu:1234@localhost:5433/edudb",
    )
    dataset_version = os.getenv("RAG_DATASET_VERSION", "law404-rag-v1")
    embedding_model = os.getenv(
        "OPENAI_EMBEDDING_MODEL",
        "text-embedding-3-small",
    )

    db_rows: list[dict] = []
    with psycopg2.connect(database_url) as conn:
        with conn.cursor() as cur:
            for collection, document_id, jsonl_path in SERVICE_CARDS:
                jsonl_row = load_jsonl_card(jsonl_path, document_id)
                expected_text = str(jsonl_row.get("chunk_text") or "").strip()
                if str(jsonl_row.get("source_type") or "") != "derived_rule":
                    errors.append(
                        f"{document_id}: JSONL source_type이 derived_rule이 아닙니다."
                    )
                if not jsonl_row.get("source_document_ids"):
                    errors.append(
                        f"{document_id}: source_document_ids가 비어 있습니다."
                    )

                cur.execute(
                    """
                    SELECT collection, document_id, source_type, title, text,
                           embedding_model, embedding IS NOT NULL
                    FROM a_part_rag_documents
                    WHERE dataset_version = %s
                      AND collection = %s
                      AND document_id = %s;
                    """,
                    (dataset_version, collection, document_id),
                )
                saved = cur.fetchall()
                if len(saved) != 1:
                    errors.append(
                        f"{document_id}: DB 행 수가 1이 아닙니다: {len(saved)}"
                    )
                    continue

                (
                    saved_collection,
                    saved_document_id,
                    source_type,
                    title,
                    text,
                    saved_embedding_model,
                    has_embedding,
                ) = saved[0]
                if str(text or "").strip() != expected_text:
                    errors.append(f"{document_id}: DB와 JSONL 본문이 다릅니다.")
                if source_type != "derived_rule":
                    errors.append(f"{document_id}: DB source_type 오류")
                if saved_embedding_model != embedding_model:
                    errors.append(f"{document_id}: embedding_model 오류")
                if not has_embedding:
                    errors.append(f"{document_id}: 임베딩이 없습니다.")

                db_rows.append(
                    {
                        "collection": saved_collection,
                        "document_id": saved_document_id,
                        "source_type": source_type,
                        "title": title,
                        "embedding_model": saved_embedding_model,
                        "has_embedding": bool(has_embedding),
                    }
                )

    code_paths = [
        PROJECT_ROOT / "backend/app/llm/a_part.py",
        PROJECT_ROOT / "backend/app/rag/retrievers/a_part.py",
        TEST_ROOT / "run_a_part_answer_eval20.py",
        TEST_ROOT / "analyze_a_part_evidence_gaps.py",
        TEST_ROOT / "ensure_a_part_service_evidence.py",
    ]
    hashes = {str(path.relative_to(PROJECT_ROOT)): sha256(path) for path in code_paths}

    payload = {
        "success": not errors,
        "validated_at": datetime.now().astimezone().isoformat(),
        "git_branch": git_value("branch", "--show-current"),
        "git_head": git_value("rev-parse", "HEAD"),
        "answer_code_version": ANSWER_CODE_VERSION,
        "search_code_version": CODE_VERSION,
        "dataset_version": dataset_version,
        "embedding_model": embedding_model,
        "answer_evaluation_summary": evaluation.get("summary"),
        "evidence_gap_summary": gap.get("summary"),
        "gap_csv_rows": gap_csv_rows,
        "service_evidence_rows": db_rows,
        "test_root_files": final_files,
        "sha256": hashes,
        "errors": errors,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("답변 코드 버전:", ANSWER_CODE_VERSION)
    print("검색 코드 버전:", CODE_VERSION)
    print("20문항 평가:", evaluation.get("summary"))
    print("근거 갭:", gap.get("summary"))
    print("서비스 규칙 DB 확인:", len(db_rows), "건")
    print("A파트 테스트 최종 파일:", final_files)
    print("최종 검증 manifest:", output_path)

    if errors:
        print()
        print("최종 검증 실패")
        for error in errors:
            print("-", error)
        raise SystemExit(1)

    print()
    print("A part 정리 후 최종 재실행 검증 통과")


if __name__ == "__main__":
    main()
