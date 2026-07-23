from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from app.consultation.a_part.router import UnsupportedConsultationIssueError
from app.graph.parts.a_part.chains import route_question

OUTPUT_DIR = Path("artifacts/a_part_upgrade_eval")

REPRESENTATIVE_QUESTIONS = [
    ("q01_owner_proxy", "집주인 아들이 대신 계약하러 왔는데 위임장이 없어요."),
    ("q02_co_owner", "공동명의 집인데 소유자 한 명만 계약하러 왔어요."),
    ("q03_owner_lessor_mismatch", "등기부 소유자와 계약서 임대인 이름이 달라요."),
    ("q04_broker_account_payment", "중개사 명의 계좌로 계약금을 보내라고 해요."),
    (
        "q05_account_change_before_contract",
        "계약 직전에 계약금 계좌가 바뀌었다고 합니다.",
    ),
    (
        "q06_broker_explanation_mismatch",
        "중개대상물 확인설명서와 계약서 내용이 달라요.",
    ),
    ("q07_mortgage", "등기부에 근저당과 채권최고액이 있어요."),
    ("q08_multiunit_priority", "다가구주택인데 선순위 보증금을 확인 못했어요."),
    ("q09_registry_restriction_warning", "등기부에 가압류가 있는데 계약해도 되나요?"),
    ("q10_trust", "신탁등기가 있는 집인데 임대차 계약을 해도 되나요?"),
    ("q11_opposability_move_in", "전입신고를 하면 대항력은 언제 생기나요?"),
    ("q12_fixed_date_priority", "확정일자와 우선변제권이 궁금해요."),
    ("q13_owner_change", "계약 후 집주인이 바뀌었다고 해요."),
    ("q14_special_clause_deposit_return", "계약금을 돌려받는 특약을 넣고 싶어요."),
    ("q15_after_contract_procedure", "계약서 작성 직후 무엇부터 해야 하나요?"),
    ("q16_lease_report", "주택 임대차신고는 언제 해야 하나요?"),
    ("q17_household_certificate", "전입세대확인서는 왜 확인해야 하나요?"),
    ("q18_address_mismatch", "계약서 주소와 등기부등본 주소가 달라요."),
    ("q19_deposit_transfer_mismatch", "계약서 보증금과 실제 이체 내역 금액이 달라요."),
    ("q20_guarantee_check", "전세보증금반환보증 가입 전에 뭘 확인해야 하나요?"),
]

PARAPHRASE_QUESTIONS = [
    ("q01_owner_proxy", "집주인 본인은 안 오고 딸이 계약하겠대요. 괜찮나요?"),
    ("q02_co_owner", "부부 공동소유인데 남편 혼자 임대차계약을 하려고 합니다."),
    ("q03_owner_lessor_mismatch", "집주인이라고 나온 사람과 등기 명의자가 다른데요."),
    (
        "q04_broker_account_payment",
        "부동산 사장님 통장으로 계약금을 먼저 넣으라고 해요.",
    ),
    (
        "q05_account_change_before_contract",
        "아까 받은 계좌 말고 다른 통장으로 보내 달라고 갑자기 바꿨어요.",
    ),
    (
        "q06_broker_explanation_mismatch",
        "확인설명서에는 없던 내용이 계약서에 적혀 있습니다.",
    ),
    ("q07_mortgage", "은행 빚이 잡힌 집인데 채권최고액이 커 보여요."),
    (
        "q08_multiunit_priority",
        "원룸 건물인데 기존 세입자 보증금 합계를 집주인이 안 알려줘요.",
    ),
    (
        "q09_registry_restriction_warning",
        "갑구에 압류 표시가 있는데 그냥 계약해도 되나요?",
    ),
    ("q10_trust", "소유자가 신탁회사로 나오는 집입니다."),
    ("q11_opposability_move_in", "이사하고 주민등록 옮기면 언제부터 보호받나요?"),
    ("q12_fixed_date_priority", "확정일자를 받으면 보증금을 먼저 돌려받을 수 있나요?"),
    ("q13_owner_change", "계약은 했는데 집이 다른 사람에게 팔렸다고 합니다."),
    (
        "q14_special_clause_deposit_return",
        "문제 생기면 계약금을 반환한다는 조항을 넣고 싶습니다.",
    ),
    (
        "q15_after_contract_procedure",
        "도장 찍고 계약한 다음에 바로 해야 하는 일이 뭐예요?",
    ),
    ("q16_lease_report", "전월세 신고 대상과 기한을 알려주세요."),
    ("q17_household_certificate", "이 집에 누가 전입돼 있는지 확인할 서류가 있나요?"),
    ("q18_address_mismatch", "동호수 표기가 계약서랑 등기 서류에서 서로 달라요."),
    (
        "q19_deposit_transfer_mismatch",
        "계약서에는 1억인데 송금한 금액은 9천만 원으로 보여요.",
    ),
    ("q20_guarantee_check", "HUG 보증을 신청하기 전에 준비할 것들이 궁금합니다."),
]

OUT_OF_SCOPE_QUESTIONS = [
    "오늘 서울 날씨가 어때요?",
    "파이썬으로 계산기 만들어줘.",
    "주식 종목을 추천해 주세요.",
    "자동차 엔진오일은 언제 갈아야 하나요?",
    "저녁 메뉴 추천해줘.",
    "영어 자기소개를 써줘.",
    "휴대폰 요금제를 비교해줘.",
    "여행 일정을 만들어주세요.",
    "고양이 사료를 추천해 주세요.",
    "노트북이 느린데 해결 방법을 알려줘.",
]

HIGH_RISK_ISSUES = {
    "q01_owner_proxy",
    "q04_broker_account_payment",
    "q05_account_change_before_contract",
    "q07_mortgage",
    "q09_registry_restriction_warning",
    "q10_trust",
    "q18_address_mismatch",
    "q19_deposit_transfer_mismatch",
}


def value_of(value: Any) -> Any:
    return getattr(value, "value", value)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * p)))
    return ordered[index]


def rate(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(bool(row.get(key)) for row in rows) / len(rows) * 100, 2)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


def run_routing_comparison() -> dict[str, Any]:
    cases = [
        *[
            (issue, "representative", question)
            for issue, question in REPRESENTATIVE_QUESTIONS
        ],
        *[(issue, "paraphrase", question) for issue, question in PARAPHRASE_QUESTIONS],
        *[
            ("OUT_OF_SCOPE", "out_of_scope", question)
            for question in OUT_OF_SCOPE_QUESTIONS
        ],
    ]

    all_rows: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    for mode_name, use_langchain in [
        ("legacy_rule", False),
        ("langchain_upgrade", True),
    ]:
        mode_rows: list[dict[str, Any]] = []
        for expected, group, question in cases:
            started = time.perf_counter()
            error = ""
            engine = ""
            confidence = None
            try:
                decision, engine = route_question(question, use_langchain=use_langchain)
                actual = decision.primary_issue_id
                confidence = decision.confidence
            except UnsupportedConsultationIssueError:
                actual = "OUT_OF_SCOPE"
                engine = "rejected"
            except Exception as exc:  # noqa: BLE001
                actual = "ERROR"
                error = f"{type(exc).__name__}: {exc}"
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            row = {
                "mode": mode_name,
                "group": group,
                "expected": expected,
                "actual": actual,
                "correct": actual == expected,
                "engine": engine,
                "confidence": confidence,
                "latency_ms": latency_ms,
                "question": question,
                "error": error,
            }
            mode_rows.append(row)
            all_rows.append(row)

        latencies = [float(row["latency_ms"]) for row in mode_rows]
        summaries[mode_name] = {
            "case_count": len(mode_rows),
            "accuracy_percent": rate(mode_rows, "correct"),
            "representative_accuracy_percent": rate(
                [row for row in mode_rows if row["group"] == "representative"],
                "correct",
            ),
            "paraphrase_accuracy_percent": rate(
                [row for row in mode_rows if row["group"] == "paraphrase"], "correct"
            ),
            "out_of_scope_rejection_percent": rate(
                [row for row in mode_rows if row["group"] == "out_of_scope"], "correct"
            ),
            "langchain_engine_percent": round(
                sum(row["engine"] == "langchain" for row in mode_rows)
                / len(mode_rows)
                * 100,
                2,
            ),
            "fallback_percent": round(
                sum("fallback" in str(row["engine"]) for row in mode_rows)
                / len(mode_rows)
                * 100,
                2,
            ),
            "average_latency_ms": round(statistics.mean(latencies), 2),
            "p95_latency_ms": round(percentile(latencies, 0.95), 2),
        }

    old_accuracy = summaries["legacy_rule"]["accuracy_percent"]
    new_accuracy = summaries["langchain_upgrade"]["accuracy_percent"]
    summaries["improvement"] = {
        "routing_accuracy_percentage_point": round(new_accuracy - old_accuracy, 2),
        "note": "같은 50개 질문을 기존 규칙 라우터와 LangChain 우선 라우터에 각각 실행한 비교값",
    }
    write_csv(OUTPUT_DIR / "routing_comparison.csv", all_rows)
    write_json(OUTPUT_DIR / "routing_summary.json", summaries)
    return summaries


def _run_live_mode(
    mode: str, *, use_langgraph: bool
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from app.consultation.a_part.chatbot_service import (
        APartChatbotService,
        ChatbotTurnRequest,
    )

    service = APartChatbotService()
    rows: list[dict[str, Any]] = []

    for expected_issue, question in REPRESENTATIVE_QUESTIONS:
        started = time.perf_counter()
        error = ""
        try:
            request = ChatbotTurnRequest(question=question)
            result = (
                service.handle(request)
                if use_langgraph
                else service._handle_without_langgraph(request)
            )
            rag = result.consultation.rag_response
            answer = getattr(rag, "answer", None)
            selected_evidence = list(getattr(rag, "selected_evidence", []) or [])
            references = list(getattr(answer, "references", []) or []) if answer else []
            immediate_actions = (
                list(getattr(answer, "immediate_actions", []) or []) if answer else []
            )
            hold_actions = (
                list(getattr(answer, "hold_actions", []) or []) if answer else []
            )
            reasons = list(getattr(answer, "reasons", []) or []) if answer else []
            core_judgment = (
                str(getattr(answer, "core_judgment", "") or "") if answer else ""
            )
            generation_status = str(value_of(getattr(rag, "generation_status", "")))
            evidence_status = str(value_of(getattr(rag, "evidence_status", "")))
            follow_up_count = len(result.consultation.follow_up_questions)
            expect_hold = expected_issue in HIGH_RISK_ISSUES
            query_used = str(getattr(rag, "query", "") or "")
            row = {
                "mode": mode,
                "expected_issue": expected_issue,
                "actual_issue": result.consultation.primary_issue_id,
                "issue_correct": result.consultation.primary_issue_id == expected_issue,
                "framework": result.orchestration.get("framework")
                if result.orchestration
                else "legacy",
                "graph_ok": result.orchestration.get("framework") == "langgraph"
                if result.orchestration
                else False,
                "route_engine": result.orchestration.get("route_engine")
                if result.orchestration
                else "legacy_rule",
                "planner_engine": result.orchestration.get("query_planner_engine")
                if result.orchestration
                else "legacy_query",
                "document_mode": result.orchestration.get("document_mode")
                if result.orchestration
                else "general",
                "answer_ready": result.answer_ready,
                "generation_status": generation_status,
                "generation_completed": generation_status == "completed",
                "evidence_status": evidence_status,
                "search_query": query_used,
                "query_rewritten": " ".join(query_used.split())
                != " ".join(question.split()),
                "search_result_count": int(getattr(rag, "search_result_count", 0) or 0),
                "selected_evidence_count": len(selected_evidence),
                "reference_count": len(references),
                "evidence_found": len(selected_evidence) > 0,
                "core_judgment_ok": bool(core_judgment.strip()),
                "immediate_actions_count": len(immediate_actions),
                "hold_actions_count": len(hold_actions),
                "reasons_count": len(reasons),
                "structure_complete": bool(
                    core_judgment.strip() and immediate_actions and reasons
                ),
                "follow_up_count": follow_up_count,
                "one_follow_up_ok": follow_up_count <= 1,
                "expect_hold": expect_hold,
                "safety_hold_ok": (not expect_hold) or bool(hold_actions),
                "risk_level": str(getattr(answer, "risk_level", "") or "")
                if answer
                else "",
                "question": question,
                "error": "",
            }
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            row = {
                "mode": mode,
                "expected_issue": expected_issue,
                "actual_issue": "ERROR",
                "issue_correct": False,
                "framework": "",
                "graph_ok": False,
                "route_engine": "",
                "planner_engine": "",
                "document_mode": "",
                "answer_ready": False,
                "generation_status": "error",
                "generation_completed": False,
                "evidence_status": "",
                "search_query": "",
                "query_rewritten": False,
                "search_result_count": 0,
                "selected_evidence_count": 0,
                "reference_count": 0,
                "evidence_found": False,
                "core_judgment_ok": False,
                "immediate_actions_count": 0,
                "hold_actions_count": 0,
                "reasons_count": 0,
                "structure_complete": False,
                "follow_up_count": 0,
                "one_follow_up_ok": False,
                "expect_hold": expected_issue in HIGH_RISK_ISSUES,
                "safety_hold_ok": False,
                "risk_level": "",
                "question": question,
                "error": error,
            }
        row["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        rows.append(row)
        print(
            f"[{mode} {len(rows):02d}/20] {expected_issue} -> {row['actual_issue']} "
            f"engine={row['route_engine']}/{row['planner_engine']} "
            f"evidence={row['selected_evidence_count']} latency={row['latency_ms']}ms"
        )

    latencies = [float(row["latency_ms"]) for row in rows]
    risk_rows = [row for row in rows if row["expect_hold"]]
    summary = {
        "mode": mode,
        "case_count": len(rows),
        "routing_accuracy_percent": rate(rows, "issue_correct"),
        "langgraph_usage_percent": rate(rows, "graph_ok"),
        "langchain_route_success_percent": round(
            sum(row["route_engine"] == "langchain" for row in rows) / len(rows) * 100, 2
        ),
        "langchain_planner_success_percent": round(
            sum(row["planner_engine"] == "langchain" for row in rows) / len(rows) * 100,
            2,
        ),
        "query_rewrite_percent": rate(rows, "query_rewritten"),
        "answer_ready_percent": rate(rows, "answer_ready"),
        "generation_completed_percent": rate(rows, "generation_completed"),
        "evidence_found_percent": rate(rows, "evidence_found"),
        "structured_answer_complete_percent": rate(rows, "structure_complete"),
        "one_follow_up_rule_percent": rate(rows, "one_follow_up_ok"),
        "high_risk_hold_action_percent": rate(risk_rows, "safety_hold_ok"),
        "average_selected_evidence_count": round(
            statistics.mean(float(row["selected_evidence_count"]) for row in rows), 2
        ),
        "average_latency_ms": round(statistics.mean(latencies), 2),
        "p50_latency_ms": round(percentile(latencies, 0.50), 2),
        "p95_latency_ms": round(percentile(latencies, 0.95), 2),
        "error_count": sum(bool(row["error"]) for row in rows),
    }
    return rows, summary


def run_live_e2e(*, compare_legacy: bool = False) -> dict[str, Any]:
    modes = [("langgraph_upgrade", True)]
    if compare_legacy:
        modes.insert(0, ("legacy_orchestration", False))

    all_rows: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    for mode, use_langgraph in modes:
        rows, summary = _run_live_mode(mode, use_langgraph=use_langgraph)
        all_rows.extend(rows)
        summaries[mode] = summary

    if compare_legacy:
        old = summaries["legacy_orchestration"]
        new = summaries["langgraph_upgrade"]
        summaries["improvement"] = {
            "routing_accuracy_percentage_point": round(
                new["routing_accuracy_percent"] - old["routing_accuracy_percent"], 2
            ),
            "generation_completed_percentage_point": round(
                new["generation_completed_percent"]
                - old["generation_completed_percent"],
                2,
            ),
            "evidence_found_percentage_point": round(
                new["evidence_found_percent"] - old["evidence_found_percent"], 2
            ),
            "structured_answer_complete_percentage_point": round(
                new["structured_answer_complete_percent"]
                - old["structured_answer_complete_percent"],
                2,
            ),
            "high_risk_hold_action_percentage_point": round(
                new["high_risk_hold_action_percent"]
                - old["high_risk_hold_action_percent"],
                2,
            ),
            "average_selected_evidence_difference": round(
                new["average_selected_evidence_count"]
                - old["average_selected_evidence_count"],
                2,
            ),
            "average_latency_difference_ms": round(
                new["average_latency_ms"] - old["average_latency_ms"], 2
            ),
            "note": "같은 현재 코드에서 기존 순차 오케스트레이션과 LangGraph 오케스트레이션을 비교한 값입니다. 완전히 별도 과거 커밋과의 비교는 아닙니다.",
        }

    write_csv(OUTPUT_DIR / "live_e2e_results.csv", all_rows)
    write_json(OUTPUT_DIR / "live_e2e_summary.json", summaries)
    return summaries


def run_multiturn() -> dict[str, Any]:
    from app.consultation.a_part.chatbot_service import (
        APartChatbotService,
        ChatbotTurnRequest,
    )

    service = APartChatbotService()
    utterances = [
        "집주인 가족이 대신 계약하러 왔어요.",
        "등기부 소유자는 김철수입니다.",
        "김철수 본인과 통화해서 아들이 대신 계약하는 데 동의한다고 확인했습니다.",
        "위임장에는 임대차계약 체결 권한이 적혀 있습니다.",
        "계약서 서명 권한도 위임장에 포함되어 있습니다.",
        "계약금과 잔금 수령 권한도 위임장에 적혀 있습니다.",
        "계약금 계좌 예금주는 소유자 김철수입니다.",
    ]

    conversation_id = None
    rows: list[dict[str, Any]] = []
    question_keys: list[str] = []
    for turn, utterance in enumerate(utterances, start=1):
        started = time.perf_counter()
        result = service.handle(
            ChatbotTurnRequest(question=utterance, conversation_id=conversation_id)
        )
        conversation_id = result.conversation_id
        follow_ups = result.consultation.follow_up_questions
        question_key = follow_ups[0].question_key if follow_ups else ""
        if question_key:
            question_keys.append(question_key)
        rows.append(
            {
                "turn": turn,
                "utterance": utterance,
                "primary_issue_id": result.consultation.primary_issue_id,
                "active_issue_kept": result.consultation.primary_issue_id
                == "q01_owner_proxy",
                "route_engine": result.orchestration.get("route_engine"),
                "follow_up_count": len(follow_ups),
                "one_follow_up_ok": len(follow_ups) <= 1,
                "next_question_key": question_key,
                "next_question": follow_ups[0].question if follow_ups else "",
                "known_fact_count": len(result.consultation.known_facts),
                "missing_fact_count": len(result.consultation.missing_facts),
                "answer_ready": result.answer_ready,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        )

    duplicates = len(question_keys) - len(set(question_keys))
    summary = {
        "turn_count": len(rows),
        "active_issue_retention_percent": rate(rows, "active_issue_kept"),
        "one_follow_up_rule_percent": rate(rows, "one_follow_up_ok"),
        "duplicate_question_count": duplicates,
        "duplicate_question_percent": round(duplicates / len(question_keys) * 100, 2)
        if question_keys
        else 0.0,
        "final_missing_fact_count": rows[-1]["missing_fact_count"],
        "final_follow_up_count": rows[-1]["follow_up_count"],
        "average_latency_ms": round(
            statistics.mean(row["latency_ms"] for row in rows), 2
        ),
    }
    write_csv(OUTPUT_DIR / "multiturn_results.csv", rows)
    write_json(OUTPUT_DIR / "multiturn_summary.json", summary)
    return summary


def run_pdf(lease_pdf: str | None, registry_pdf: str | None) -> dict[str, Any]:
    from app.consultation.a_part.chatbot_service import (
        APartChatbotService,
        ChatbotTurnRequest,
    )
    from app.consultation.a_part.models import create_conversation_state
    from app.documents.models import DocumentType

    if not lease_pdf and not registry_pdf:
        return {
            "skipped": True,
            "reason": "--lease-pdf 또는 --registry-pdf를 지정하지 않았습니다.",
        }

    service = APartChatbotService()
    state = create_conversation_state("q15_after_contract_procedure")
    stored = service.conversation_service.store.create(state)
    document_ids: list[str] = []

    if lease_pdf:
        path = Path(lease_pdf).expanduser().resolve()
        upload = service.document_service.upload_bytes(
            conversation_id=stored.conversation_id,
            document_type=DocumentType.LEASE_CONTRACT,
            filename=path.name,
            content_type="application/pdf",
            data=path.read_bytes(),
        )
        document_ids.append(upload.document.document_id)

    if registry_pdf:
        path = Path(registry_pdf).expanduser().resolve()
        upload = service.document_service.upload_bytes(
            conversation_id=stored.conversation_id,
            document_type=DocumentType.REGISTRY,
            filename=path.name,
            content_type="application/pdf",
            data=path.read_bytes(),
        )
        document_ids.append(upload.document.document_id)

    if lease_pdf and registry_pdf:
        question = (
            "첨부한 계약서와 등기부등본을 비교해서 다른 내용과 위험 요소를 알려주세요."
        )
        expected_mode = "combined_documents"
    elif lease_pdf:
        question = "첨부한 계약서를 분석해서 위험하거나 빠진 내용을 알려주세요."
        expected_mode = "lease_contract"
    else:
        question = "첨부한 등기부등본을 분석해서 소유자와 권리관계를 알려주세요."
        expected_mode = "registry"

    started = time.perf_counter()
    result = service.handle(
        ChatbotTurnRequest(
            question=question,
            conversation_id=stored.conversation_id,
            document_ids=document_ids,
            analyze_documents=True,
        )
    )
    analysis = result.document_analysis
    summary = {
        "expected_mode": expected_mode,
        "actual_mode": result.orchestration.get("document_mode"),
        "document_mode_correct": result.orchestration.get("document_mode")
        == expected_mode,
        "framework": result.orchestration.get("framework"),
        "analysis_created": analysis is not None,
        "lease_analysis_count": len(getattr(analysis, "lease_analyses", []) or [])
        if analysis
        else 0,
        "registry_analysis_count": len(getattr(analysis, "registry_analyses", []) or [])
        if analysis
        else 0,
        "comparison_created": bool(getattr(analysis, "comparison", None))
        if analysis
        else False,
        "warning_count": len(result.warnings),
        "answer_ready": result.answer_ready,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    write_json(OUTPUT_DIR / "pdf_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--routing", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--live-compare", action="store_true")
    parser.add_argument("--multiturn", action="store_true")
    parser.add_argument("--lease-pdf")
    parser.add_argument("--registry-pdf")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    if args.all or args.routing:
        results["routing"] = run_routing_comparison()
    if args.all or args.live or args.live_compare:
        results["live_e2e"] = run_live_e2e(compare_legacy=args.live_compare)
    if args.all or args.multiturn:
        results["multiturn"] = run_multiturn()
    if args.lease_pdf or args.registry_pdf:
        results["pdf"] = run_pdf(args.lease_pdf, args.registry_pdf)
    if not results:
        parser.error(
            "--routing, --live, --live-compare, --multiturn, --all 또는 PDF 경로를 지정하세요."
        )

    write_json(OUTPUT_DIR / "latest_summary.json", results)
    print("\n=== A파트 고도화 평가 요약 ===")
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    print(f"\n결과 저장 위치: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
