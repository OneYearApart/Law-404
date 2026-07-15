from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / "backend" / ".env")
load_dotenv(PROJECT_ROOT / ".env")

from backend.app.consultation.a_part.chatbot_service import (
    APartChatbotService,
    ChatbotProcessingStatus,
    ChatbotTurnRequest,
)
from backend.app.consultation.a_part.document_service import APartDocumentUploadService
from backend.app.consultation.a_part.models import SlotStatus, create_conversation_state
from backend.app.consultation.a_part.question_builder import FollowUpQuestion
from backend.app.consultation.a_part.router import route_issues
from backend.app.consultation.a_part.service import APartConversationService
from backend.app.consultation.a_part.state_updater import SlotExtractionResult
from backend.app.consultation.a_part.store import MemoryConversationStore
from backend.tests.a_part.run_search_answer20 import EVAL_CASES
from backend.tests.a_part.run_pdf_documents import (
    build_cases as build_pdf_cases,
    discover_files,
)


class NoopSlotExtractor:
    """테스트에서 명시적으로 전달한 체크리스트 값만 상태에 반영한다."""

    def extract(self, *, user_text: str, state: Any) -> SlotExtractionResult:
        return SlotExtractionResult(updates=[])


FAILED_STATUSES = {
    ChatbotProcessingStatus.RAG_EVIDENCE_NOT_FOUND,
    ChatbotProcessingStatus.RAG_SEARCH_FAILED,
    ChatbotProcessingStatus.RAG_GENERATION_FAILED,
    ChatbotProcessingStatus.RAG_VALIDATION_FAILED,
}

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

FINAL_SUMMARY_PROMPT = (
    "지금까지 확인한 내용을 기준으로 현재 위험 수준, 남은 확인사항, "
    "지금 해야 할 행동을 최종 정리해 주세요."
)

PDF_FOLLOW_UP_PROMPTS: dict[str, list[str]] = {
    "q21_lease_pdf": [
        "OCR로 확인된 계약 당사자·주소·금액·날짜 중 원본에서 다시 확인할 항목을 알려 주세요.",
        "등기부가 아직 없을 때 지금 보류하거나 먼저 확인해야 할 행동을 알려 주세요.",
        "지금까지의 계약서 분석을 기준으로 최종 행동 순서를 세 단계로 정리해 주세요.",
    ],
    "q22_registry_pdf": [
        "계약서 임대인과 등기부 소유자, 목적물 주소가 일치하는지 다시 설명해 주세요.",
        "현재 유효한 근저당·압류·가압류·신탁 기록과 말소된 기록을 구분해 주세요.",
        "잔금 직전에 다시 확인할 항목을 우선순위대로 정리해 주세요.",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="A파트 실제 서비스형 다중 멀티턴 상담만 검증"
    )
    parser.add_argument("--downloads", type=Path, default=Path.home() / "Downloads")
    parser.add_argument("--json-output", type=Path)
    return parser.parse_args()


def _sample_value(slot_key: str, label: str) -> tuple[Any, str]:
    key = slot_key.lower()
    if any(token in key for token in ("amount", "value", "deposits", "balance", "rent")):
        return 150_000_000, f"{label}은 150,000,000원입니다."
    if any(token in key for token in ("date", "deadline", "period", "timing")):
        return "2026-07-14", f"{label}은 2026-07-14로 확인했습니다."
    if "address" in key:
        value = "서울특별시 마포구 신공덕동 5-75 갑을명가시티 제201호"
        return value, f"{label}은 {value}입니다."
    if any(token in key for token in ("name", "owner", "holder", "trustee", "creditor", "counterparty")):
        return "홍길동", f"{label}은 홍길동입니다."
    if any(token in key for token in ("reason", "type", "relationship", "method", "source", "fields", "scope")):
        return "원본 문서로 확인 완료", f"{label}은 원본 문서로 확인했습니다."
    return True, f"{label}은 확인했습니다."


def _answer_text(result: Any) -> str:
    answer = result.consultation.rag_response.answer
    lines = [
        f"위험 수준: {answer.risk_level}",
        f"핵심 판단: {answer.core_judgment}",
        "지금 해야 할 행동:",
    ]
    lines.extend(
        f"  {index}. {item}"
        for index, item in enumerate(answer.immediate_actions, 1)
    )
    lines.append("우선 보류해야 할 행동:")
    if answer.hold_actions:
        lines.extend(
            f"  {index}. {item}"
            for index, item in enumerate(answer.hold_actions, 1)
        )
    else:
        lines.append("  없음")
    followups = result.consultation.follow_up_questions
    lines.append("추가 질문:")
    if followups:
        lines.extend(
            f"  {index}. [{item.issue_id}:{item.slot_key}] {item.question}"
            for index, item in enumerate(followups, 1)
        )
    else:
        lines.append("  없음")
    references = getattr(answer, "references", []) or []
    lines.append(f"근거 수: {len(references)}")
    for item in references[:3]:
        title = getattr(item, "title", None) or (
            item.get("title") if isinstance(item, dict) else ""
        )
        collection = getattr(item, "collection", None) or (
            item.get("collection") if isinstance(item, dict) else ""
        )
        lines.append(f"  - {collection}: {title}")
    return "\n".join(lines)


def _validate_turn(
    result: Any,
    *,
    expected_conversation_id: str | None,
    expected_turn_count: int,
) -> list[str]:
    failures: list[str] = []
    if expected_conversation_id and result.conversation_id != expected_conversation_id:
        failures.append("conversation_id가 이전 턴과 달라짐")
    if expected_turn_count > 1 and result.is_new_conversation:
        failures.append("후속 턴이 새 상담으로 생성됨")
    if not result.answer_ready:
        failures.append("answer_ready가 false")
    if result.processing_status in FAILED_STATUSES:
        failures.append(f"실패 처리 상태: {result.processing_status.value}")

    answer = result.consultation.rag_response.answer
    if not str(answer.core_judgment).strip():
        failures.append("핵심 판단이 비어 있음")
    if not answer.immediate_actions:
        failures.append("지금 해야 할 행동이 비어 있음")
    if len(answer.immediate_actions) > 3:
        failures.append("지금 해야 할 행동이 3개 초과")
    if len(answer.follow_up_questions) > 3:
        failures.append("답변 내부 추가 질문이 3개 초과")
    if not answer.references:
        failures.append("법률 근거·참고 자료가 비어 있음")

    state = result.consultation.state
    if state.turn_count != expected_turn_count:
        failures.append(
            f"turn_count 오류: expected={expected_turn_count}, actual={state.turn_count}"
        )
    expected_messages = expected_turn_count * 2
    if len(state.messages) != expected_messages:
        failures.append(
            f"메시지 수 오류: expected={expected_messages}, actual={len(state.messages)}"
        )
    return failures


def _reference_collections(result: Any) -> set[str]:
    collections: set[str] = set()
    for item in result.consultation.rag_response.answer.references:
        value = getattr(item, "collection", None)
        if value:
            collections.add(str(value))
    return collections


def _select_followup(
    result: Any,
    *,
    answered_keys: set[str],
) -> FollowUpQuestion | None:
    for item in result.consultation.follow_up_questions:
        key = f"{item.issue_id}:{item.slot_key}"
        if key not in answered_keys:
            return item

    state = result.consultation.state
    for issue_id, slot in state.missing_slots():
        key = f"{issue_id}:{slot.key}"
        if key in answered_keys:
            continue
        return FollowUpQuestion(
            issue_id=issue_id,
            slot_key=slot.key,
            label=slot.label,
            question=slot.question,
            status=slot.status,
            risk_critical=slot.risk_critical,
        )
    return None


def _validate_applied_slot(
    result: Any,
    *,
    issue_id: str,
    slot_key: str,
    expected_value: Any,
) -> list[str]:
    failures: list[str] = []
    if not result.consultation.applied_updates:
        failures.append("체크리스트 값이 상태에 반영되지 않음")
    slot = result.consultation.state.issue_slots.get(issue_id, {}).get(slot_key)
    if slot is None:
        failures.append(f"반영 대상 슬롯을 찾을 수 없음: {issue_id}:{slot_key}")
        return failures
    if slot.status != SlotStatus.CONFIRMED:
        failures.append(
            f"슬롯 상태 오류: {issue_id}:{slot_key}={slot.status.value}"
        )
    if slot.value != expected_value:
        failures.append(
            f"슬롯 값 오류: {issue_id}:{slot_key} expected={expected_value!r}, actual={slot.value!r}"
        )
    return failures


def run_text_multiturn(total_turns: int) -> tuple[dict[str, int], list[dict[str, Any]]]:
    if total_turns < 3:
        raise ValueError("자연어 멀티턴은 최소 3턴 이상이어야 합니다.")

    print("=" * 116)
    print(
        f"실제 서비스형 자연어 상담 20문항 다중 멀티턴 "
        f"— 문항당 {total_turns}턴"
    )
    print("=" * 116)

    summary = Counter(PASS=0, FAIL=0, ERROR=0)
    results: list[dict[str, Any]] = []

    store = MemoryConversationStore()
    conversation_service = APartConversationService(
        store=store,
        slot_extractor=NoopSlotExtractor(),
    )
    chatbot = APartChatbotService(conversation_service=conversation_service)

    for case_index, case in enumerate(EVAL_CASES, 1):
        failures: list[str] = []
        turn_records: list[dict[str, Any]] = []
        answered_keys: set[str] = set()
        conversation_id: str | None = None
        previous: Any | None = None

        print()
        print("=" * 116)
        print(f"[{case_index}/20] {case.question_id}")
        print("=" * 116)

        try:
            for turn_no in range(1, total_turns + 1):
                checklist_updates: list[dict[str, Any]] = []
                selected_key: str | None = None
                selected_value: Any = None

                if turn_no == 1:
                    user_text = case.question
                elif turn_no == total_turns:
                    user_text = FINAL_SUMMARY_PROMPT
                else:
                    selected = _select_followup(
                        previous,
                        answered_keys=answered_keys,
                    )
                    if selected is None:
                        user_text = (
                            "방금 답변을 기준으로 아직 확인되지 않은 사실과 "
                            "다음 행동을 이어서 설명해 주세요."
                        )
                    else:
                        selected_key = f"{selected.issue_id}:{selected.slot_key}"
                        answered_keys.add(selected_key)
                        selected_value, user_text = _sample_value(
                            selected.slot_key,
                            selected.label,
                        )
                        checklist_updates.append(
                            {
                                "issue_id": selected.issue_id,
                                "slot_key": selected.slot_key,
                                "status": SlotStatus.CONFIRMED,
                                "value": selected_value,
                                "evidence_text": user_text,
                            }
                        )

                print(f"사용자 {turn_no}: {user_text}")
                print("-" * 116)
                response = chatbot.handle(
                    ChatbotTurnRequest(
                        question=user_text,
                        conversation_id=conversation_id,
                        issue_id=case.question_id,
                        checklist_updates=checklist_updates,
                        analyze_documents=False,
                        rag_options={
                            "search_top_k": case.search_top_k,
                            "answer_evidence_count": case.answer_evidence_count,
                            "min_similarity": case.min_similarity,
                            "candidate_k": case.candidate_k,
                        },
                    )
                )
                print(f"챗봇 {turn_no}:")
                print(_answer_text(response))

                if turn_no == 1:
                    conversation_id = response.conversation_id
                    if response.consultation.primary_issue_id != case.question_id:
                        failures.append(
                            "라우팅 불일치: "
                            f"expected={case.question_id}, "
                            f"actual={response.consultation.primary_issue_id}"
                        )
                    expected = EXPECTED_COLLECTIONS[case.question_id]
                    actual_collections = _reference_collections(response)
                    if not (actual_collections & expected):
                        failures.append(
                            "기대 collection 미포함: "
                            f"expected={sorted(expected)}, "
                            f"actual={sorted(actual_collections)}"
                        )

                failures.extend(
                    _validate_turn(
                        response,
                        expected_conversation_id=conversation_id,
                        expected_turn_count=turn_no,
                    )
                )

                if checklist_updates and selected_key is not None:
                    issue_id, slot_key = selected_key.split(":", 1)
                    failures.extend(
                        _validate_applied_slot(
                            response,
                            issue_id=issue_id,
                            slot_key=slot_key,
                            expected_value=selected_value,
                        )
                    )

                turn_records.append(
                    {
                        "turn": turn_no,
                        "user": user_text,
                        "processing_status": response.processing_status.value,
                        "turn_count": response.consultation.state.turn_count,
                        "message_count": len(response.consultation.state.messages),
                        "selected_slot": selected_key,
                    }
                )
                previous = response
                print()

            final_state = previous.consultation.state
            if final_state.turn_count != total_turns:
                failures.append(
                    f"최종 turn_count 오류: {final_state.turn_count}"
                )
            if len(final_state.messages) != total_turns * 2:
                failures.append(
                    f"최종 메시지 수 오류: {len(final_state.messages)}"
                )
            if len(answered_keys) < 1:
                failures.append("후속 슬롯이 한 번도 상태에 반영되지 않음")

            status = "FAIL" if failures else "PASS"
            summary[status] += 1
            print("자동 평가 →", status)
            for item in failures:
                print("-", item)
            results.append(
                {
                    "id": case.question_id,
                    "status": status,
                    "conversation_id": conversation_id,
                    "turns": total_turns,
                    "answered_slot_count": len(answered_keys),
                    "failures": failures,
                    "turn_records": turn_records,
                }
            )
        except Exception as exc:
            summary["ERROR"] += 1
            print("자동 평가 → ERROR")
            print("-", repr(exc))
            results.append(
                {
                    "id": case.question_id,
                    "status": "ERROR",
                    "conversation_id": conversation_id,
                    "failures": [repr(exc)],
                    "turn_records": turn_records,
                }
            )

    return dict(summary), results


def run_pdf_multiturn(
    downloads: Path,
    total_turns: int,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    if total_turns < 3:
        raise ValueError("PDF 멀티턴은 최소 3턴 이상이어야 합니다.")

    print()
    print("=" * 116)
    print(
        f"실제 서비스형 PDF 상담 2문항 다중 멀티턴 "
        f"— 문항당 {total_turns}턴"
    )
    print("=" * 116)

    args = argparse.Namespace(
        lease_pdf=None,
        registry_pdfs=None,
        local_only=False,
    )
    files = discover_files(downloads.resolve(), args)
    cases = build_pdf_cases(files)

    summary = Counter(PASS=0, FAIL=0, ERROR=0)
    results: list[dict[str, Any]] = []

    with TemporaryDirectory(prefix="law404-service-multiturn-pdf-") as temp_dir:
        store = MemoryConversationStore()
        conversation_service = APartConversationService(
            store=store,
            slot_extractor=NoopSlotExtractor(),
        )
        document_service = APartDocumentUploadService(
            conversation_service=conversation_service,
            storage_root=Path(temp_dir) / "storage",
        )
        chatbot = APartChatbotService(
            conversation_service=conversation_service,
            document_service=document_service,
        )

        for case_index, case in enumerate(cases, 1):
            failures: list[str] = []
            turn_records: list[dict[str, Any]] = []
            conversation_id: str | None = None

            print()
            print("=" * 116)
            print(f"[{case_index}/2] {case.evaluation_id}")
            print("=" * 116)

            try:
                routed = route_issues(case.question)
                state = store.create(
                    create_conversation_state(
                        primary_issue_id=routed.primary_issue_id,
                        related_issue_ids=list(routed.related_issue_ids),
                    )
                )
                conversation_id = state.conversation_id
                document_ids: list[str] = []

                print("PDF 업로드·OCR 추출")
                print("-" * 116)
                for path, document_type in case.documents:
                    uploaded = document_service.upload_bytes(
                        conversation_id=conversation_id,
                        document_type=document_type,
                        filename=path.name,
                        content_type="application/pdf",
                        data=path.read_bytes(),
                    )
                    document_id = uploaded.document.document_id
                    document_ids.append(document_id)
                    extraction_response = document_service.extract_document(
                        conversation_id=conversation_id,
                        document_id=document_id,
                        force=True,
                    )
                    extraction = extraction_response.extraction
                    print(
                        f"→ {path.name} | document_id={document_id} "
                        f"| status={extraction.processing_status.value} "
                        f"| pages={extraction.page_count} "
                        f"| chars={extraction.text_character_count}"
                    )

                prompts = PDF_FOLLOW_UP_PROMPTS[case.evaluation_id]
                if total_turns - 1 > len(prompts):
                    prompts = [
                        *prompts,
                        *(
                            FINAL_SUMMARY_PROMPT
                            for _ in range(total_turns - 1 - len(prompts))
                        ),
                    ]
                else:
                    prompts = prompts[: total_turns - 1]

                previous: Any | None = None
                for turn_no in range(1, total_turns + 1):
                    user_text = case.question if turn_no == 1 else prompts[turn_no - 2]
                    print()
                    print(f"사용자 {turn_no}: {user_text}")
                    print("-" * 116)

                    response = chatbot.handle(
                        ChatbotTurnRequest(
                            question=user_text,
                            conversation_id=conversation_id,
                            issue_id=routed.primary_issue_id,
                            related_issue_ids=list(routed.related_issue_ids),
                            document_ids=(document_ids if turn_no == 1 else []),
                            analyze_documents=True,
                            force_document_analysis=(turn_no == 1),
                        )
                    )
                    print(f"챗봇 {turn_no}:")
                    print(_answer_text(response))

                    failures.extend(
                        _validate_turn(
                            response,
                            expected_conversation_id=conversation_id,
                            expected_turn_count=turn_no,
                        )
                    )
                    if turn_no == 1 and response.document_analysis is None:
                        failures.append("첫 번째 턴 문서 분석 결과가 없음")

                    connected_ids = {
                        item.document_id
                        for item in response.consultation.state.documents
                    }
                    if not set(document_ids).issubset(connected_ids):
                        failures.append(
                            f"상담 상태에서 PDF 연결 유실: turn={turn_no}"
                        )

                    turn_records.append(
                        {
                            "turn": turn_no,
                            "user": user_text,
                            "processing_status": response.processing_status.value,
                            "turn_count": response.consultation.state.turn_count,
                            "message_count": len(response.consultation.state.messages),
                            "document_count": len(response.consultation.state.documents),
                        }
                    )
                    previous = response

                final_state = previous.consultation.state
                if final_state.turn_count != total_turns:
                    failures.append(
                        f"PDF 최종 turn_count 오류: {final_state.turn_count}"
                    )
                if len(final_state.messages) != total_turns * 2:
                    failures.append(
                        f"PDF 최종 메시지 수 오류: {len(final_state.messages)}"
                    )

                status = "FAIL" if failures else "PASS"
                summary[status] += 1
                print("자동 평가 →", status)
                for item in failures:
                    print("-", item)
                results.append(
                    {
                        "id": case.evaluation_id,
                        "status": status,
                        "conversation_id": conversation_id,
                        "turns": total_turns,
                        "document_ids": document_ids,
                        "failures": failures,
                        "turn_records": turn_records,
                    }
                )
            except Exception as exc:
                summary["ERROR"] += 1
                print("자동 평가 → ERROR")
                print("-", repr(exc))
                results.append(
                    {
                        "id": case.evaluation_id,
                        "status": "ERROR",
                        "conversation_id": conversation_id,
                        "failures": [repr(exc)],
                        "turn_records": turn_records,
                    }
                )

    return dict(summary), results


TEXT_TURNS = 5
PDF_TURNS = 4


def run_all(downloads: Path) -> dict[str, Any]:
    text_turns = TEXT_TURNS
    pdf_turns = PDF_TURNS
    text_summary, text_results = run_text_multiturn(text_turns)
    pdf_summary, pdf_results = run_pdf_multiturn(downloads, pdf_turns)

    total_pass = text_summary.get("PASS", 0) + pdf_summary.get("PASS", 0)
    total_fail = text_summary.get("FAIL", 0) + pdf_summary.get("FAIL", 0)
    total_error = text_summary.get("ERROR", 0) + pdf_summary.get("ERROR", 0)
    final = "PASS" if (total_pass, total_fail, total_error) == (22, 0, 0) else "FAIL"

    text_total_turns = 20 * text_turns
    pdf_total_turns = 2 * pdf_turns

    print()
    print("=" * 116)
    print("A파트 실제 서비스형 다중 멀티턴 상담 최종 요약")
    print("-" * 116)
    print(
        f"자연어 상담: 20문항 × {text_turns}턴 = {text_total_turns}턴 "
        f"| PASS {text_summary.get('PASS', 0)} "
        f"/ FAIL {text_summary.get('FAIL', 0)} "
        f"/ ERROR {text_summary.get('ERROR', 0)}"
    )
    print(
        f"PDF 상담: 2문항 × {pdf_turns}턴 = {pdf_total_turns}턴 "
        f"| PASS {pdf_summary.get('PASS', 0)} "
        f"/ FAIL {pdf_summary.get('FAIL', 0)} "
        f"/ ERROR {pdf_summary.get('ERROR', 0)}"
    )
    print(
        f"전체 사용자 질문·챗봇 답변 쌍: "
        f"{text_total_turns + pdf_total_turns}턴"
    )
    print(f"상담 시나리오: PASS {total_pass} / FAIL {total_fail} / ERROR {total_error}")
    print("다중 멀티턴 최종 판정:", final)
    print("=" * 116)

    return {
        "configuration": {
            "text_cases": 20,
            "text_turns_per_case": text_turns,
            "text_total_turns": text_total_turns,
            "pdf_cases": 2,
            "pdf_turns_per_case": pdf_turns,
            "pdf_total_turns": pdf_total_turns,
            "all_total_turns": text_total_turns + pdf_total_turns,
        },
        "text_summary": text_summary,
        "pdf_summary": pdf_summary,
        "total": {
            "PASS": total_pass,
            "FAIL": total_fail,
            "ERROR": total_error,
        },
        "final": final,
        "results": [*text_results, *pdf_results],
    }


def main() -> None:
    args = parse_args()
    result = run_all(args.downloads.expanduser().resolve())
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print("JSON 결과 저장:", args.json_output)
    if result["final"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
