from __future__ import annotations

import argparse
import math
import os
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path.cwd().resolve()
if not (ROOT / "backend").is_dir():
    raise SystemExit(
        "프로젝트 루트에서 실행해야 합니다.\n"
        "예: cd /Users/leeunduck/project/AIMiniProject/Law-404"
    )
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
except ImportError as exc:
    raise SystemExit("python-dotenv가 필요합니다: pip install python-dotenv") from exc

load_dotenv(ROOT / "backend" / ".env")
load_dotenv(ROOT / ".env")

from backend.app.consultation.a_part.chatbot_service import (
    APartChatbotService,
    ChatbotProcessingStatus,
    ChatbotTurnRequest,
)
from backend.app.consultation.a_part.document_service import APartDocumentUploadService
from backend.app.consultation.a_part.models import create_conversation_state
from backend.app.consultation.a_part.router import route_issues
from backend.app.consultation.a_part.service import APartConversationService
from backend.app.consultation.a_part.state_updater import SlotExtractionResult
from backend.app.consultation.a_part.store import MemoryConversationStore
from backend.app.documents.analysis.models import AnalysisValueStatus, ComparisonStatus
from backend.app.documents.models import DocumentProcessingStatus, DocumentType
from backend.app.llm.a_part import (
    EvidenceStatus,
    RAGGenerationStatus,
    format_answer_for_console,
)


class NoopSlotExtractor:
    """질문 문장에서 사실을 추측하지 않고 문서 분석 결과만 상태에 반영한다."""

    def extract(self, *, user_text, state) -> SlotExtractionResult:
        return SlotExtractionResult(updates=[])


@dataclass(frozen=True, slots=True)
class FileSet:
    lease_pdf: Path
    registry_pdfs: tuple[Path, Path, Path]


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    evaluation_id: str
    label: str
    documents: tuple[tuple[Path, DocumentType], ...]
    question: str

    @property
    def is_registry_case(self) -> bool:
        return self.evaluation_id == "q22_registry_pdf"


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def path_label(path: Path) -> str:
    return nfc(path.name)


def content_type(path: Path) -> str:
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"PDF 파일만 지원합니다: {path}")
    return "application/pdf"


def choose_latest(paths: list[Path], *, label: str) -> Path:
    if not paths:
        raise FileNotFoundError(f"Downloads에서 {label} 파일을 찾지 못했습니다.")
    return sorted(paths, key=lambda item: (item.stat().st_mtime_ns, item.name))[-1]


def discover_files(downloads: Path, args: argparse.Namespace) -> FileSet:
    explicit_all = args.lease_pdf is not None and args.registry_pdfs is not None
    if not downloads.is_dir() and not explicit_all:
        raise FileNotFoundError(f"Downloads 폴더가 없습니다: {downloads}")

    pdf_files = (
        [
            item for item in downloads.rglob("*")
            if item.is_file() and item.suffix.lower() == ".pdf"
        ]
        if downloads.is_dir()
        else []
    )

    def normalized_stem(path: Path) -> str:
        return re.sub(r"[^0-9a-z가-힣]", "", nfc(path.stem).lower())

    def resolve_explicit(path: Path | None, label: str) -> Path | None:
        if path is None:
            return None
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"직접 지정한 {label} 파일이 없습니다: {resolved}")
        if resolved.suffix.lower() != ".pdf":
            raise ValueError(f"{label}은 PDF여야 합니다: {resolved}")
        return resolved

    lease_pdf = resolve_explicit(args.lease_pdf, "계약서 PDF")
    if lease_pdf is None:
        candidates = [
            item for item in pdf_files
            if "계약서" in normalized_stem(item)
            and "등기부" not in normalized_stem(item)
        ]
        lease_pdf = choose_latest(candidates, label="계약서 PDF")

    if args.registry_pdfs:
        registry_pdfs = tuple(
            resolve_explicit(path, f"등기부등본 {index} PDF")
            for index, path in enumerate(args.registry_pdfs, start=1)
        )
    else:
        grouped: dict[int, list[Path]] = {1: [], 2: [], 3: []}
        for item in pdf_files:
            match = re.search(r"등기부등본([123])", normalized_stem(item))
            if match:
                grouped[int(match.group(1))].append(item)
        registry_pdfs = tuple(
            choose_latest(grouped[index], label=f"등기부등본 {index} PDF")
            for index in (1, 2, 3)
        )

    result = FileSet(
        lease_pdf=lease_pdf,
        registry_pdfs=registry_pdfs,  # type: ignore[arg-type]
    )
    validate_file_set(result)
    return result


def validate_file_set(files: FileSet) -> None:
    all_paths = [files.lease_pdf, *files.registry_pdfs]
    missing = [str(path) for path in all_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("다음 파일이 없습니다:\n- " + "\n- ".join(missing))
    if any(path.suffix.lower() != ".pdf" for path in all_paths):
        raise ValueError("최종 테스트에는 PDF만 사용할 수 있습니다.")
    if len({path.resolve() for path in all_paths}) != len(all_paths):
        raise ValueError("같은 PDF가 두 위치에 중복 배정됐습니다.")
    empty = [str(path) for path in all_paths if path.stat().st_size <= 0]
    if empty:
        raise ValueError("빈 PDF가 있습니다:\n- " + "\n- ".join(empty))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="실제 계약서 1개와 등기부 PDF 3개로 업로드·OCR·분석·비교·상담을 검증합니다."
    )
    parser.add_argument(
        "--downloads",
        type=Path,
        default=Path.home() / "Downloads",
        help="실제 PDF가 있는 Downloads 폴더",
    )
    parser.add_argument("--lease-pdf", type=Path, help="계약서 PDF 직접 경로")
    parser.add_argument(
        "--registry-pdfs",
        type=Path,
        nargs=3,
        metavar=("PAGE1", "PAGE2", "PAGE3"),
        help="등기부등본 PDF 1·2·3페이지 직접 경로",
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="OpenAI·RAG 답변을 제외하고 업로드·OCR·분석·비교만 실행",
    )
    return parser.parse_args()


def field(analysis: Any, key: str):
    return analysis.fields.get(key)


def field_value(analysis: Any, key: str):
    item = field(analysis, key)
    return None if item is None else item.value


def compact(value: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", nfc(str(value)).lower())


def digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def amount_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return int(value)
    number = digits(value)
    return int(number) if number else None


def available(item: Any) -> bool:
    return (
        item is not None
        and item.status != AnalysisValueStatus.UNKNOWN
        and item.value is not None
        and item.value != ""
        and item.value != []
    )


def owner_contains(value: Any, expected: str) -> bool:
    values = value if isinstance(value, list) else [value]
    expected_compact = compact(expected)
    return any(expected_compact in compact(item) for item in values if item is not None)


def print_file_mapping(files: FileSet) -> None:
    print("실제 PDF 매핑")
    print(f"q21 계약서 PDF: {files.lease_pdf}")
    for index, path in enumerate(files.registry_pdfs, start=1):
        print(f"q22 등기부 PDF {index}/3: {path}")


def print_extractions(extractions: list[Any]) -> None:
    total_pages = sum(item.page_count for _, item in extractions)
    direct_pages = sum(item.direct_text_page_count for _, item in extractions)
    ocr_pages = sum(item.ocr_page_count for _, item in extractions)
    characters = sum(item.text_character_count for _, item in extractions)
    seconds = sum(item.total_seconds for _, item in extractions)
    print("문서 추출 결과")
    for path, item in extractions:
        print(
            f"→ {path_label(path)} | status={item.processing_status.value} | "
            f"method={item.extraction_method.value} | pages={item.page_count} | "
            f"direct={item.direct_text_page_count} | ocr={item.ocr_page_count} | "
            f"chars={item.text_character_count} | seconds={item.total_seconds:.3f}"
        )
        for warning in item.warnings:
            print(f"  경고: {warning}")
    print(
        f"→ 합계: pages={total_pages}, direct={direct_pages}, ocr={ocr_pages}, "
        f"chars={characters}, seconds={seconds:.3f}"
    )


def print_analysis(response: Any) -> None:
    if response.lease_analyses:
        analysis = response.lease_analyses[-1]
        print("계약서 분석")
        for key in (
            "lessor_name", "lessee_name", "property_address",
            "deposit_amount", "contract_payment", "balance_payment",
            "contract_date", "move_in_date", "contract_start_date", "contract_end_date",
        ):
            item = field(analysis, key)
            if item is not None:
                print(
                    f"→ {key}: status={item.status.value}, "
                    f"value={item.value!r}, confidence={item.confidence:.3f}"
                )
        print(f"→ 특약 수: {len(analysis.special_clauses)}")
        print(f"→ 분석 경고: {analysis.warnings}")

    if response.registry_analyses:
        analysis = response.registry_analyses[-1]
        print("등기부 분석")
        for key in (
            "registry_address", "current_owners", "co_owner_exists",
            "mortgage_exists", "maximum_secured_amount",
            "active_restriction_exists", "restriction_types",
            "trust_registration_exists", "trustees", "latest_registry_checked",
        ):
            item = field(analysis, key)
            if item is not None:
                print(
                    f"→ {key}: status={item.status.value}, "
                    f"value={item.value!r}, confidence={item.confidence:.3f}"
                )
        print(f"→ 근저당 항목 수: {len(analysis.mortgages)}")
        print(f"→ 권리 제한 항목 수: {len(analysis.restrictions)}")
        print(f"→ 신탁 항목 수: {len(analysis.trusts)}")
        print(f"→ 분석 경고: {analysis.warnings}")

    print("상담 상태 반영")
    print(f"→ 추가 issue: {response.state_mapping.added_issue_ids}")
    print(f"→ 반영 슬롯 수: {len(response.state_mapping.applied)}")
    print(f"→ 문서 기준 위험 수준: {response.state_mapping.risk_level}")

    if response.comparison is not None and response.comparison.comparisons:
        print("계약서·등기부 비교")
        for item in response.comparison.comparisons:
            print(
                f"→ {item.key}: status={item.status.value}, "
                f"left={item.left_value!r}, right={item.right_value!r}"
            )
            print(f"  설명: {item.explanation}")


def validate_extractions(case: EvaluationCase, extractions: list[Any]) -> list[str]:
    failures: list[str] = []
    if len(extractions) != len(case.documents):
        failures.append("업로드 파일 수와 추출 결과 수가 다름")
    total_ocr = 0
    total_chars = 0
    total_pages = 0
    for path, extraction in extractions:
        if extraction.processing_status not in {
            DocumentProcessingStatus.COMPLETED,
            DocumentProcessingStatus.PARTIAL,
        }:
            failures.append(
                f"추출 실패 상태: {path_label(path)}={extraction.processing_status.value}"
            )
        if not extraction.combined_text.strip():
            failures.append(f"추출 텍스트가 비어 있음: {path_label(path)}")
        if extraction.page_count < 1:
            failures.append(f"페이지 수가 1 미만: {path_label(path)}")
        if extraction.text_character_count < 30:
            failures.append(
                f"추출 문자 수가 너무 적음: {path_label(path)}={extraction.text_character_count}"
            )
        total_ocr += extraction.ocr_page_count
        total_chars += extraction.text_character_count
        total_pages += extraction.page_count

    expected_pages = len(case.documents)
    if total_pages != expected_pages:
        failures.append(
            f"전체 페이지 수가 예상과 다름: expected={expected_pages}, actual={total_pages}"
        )
    if total_ocr < expected_pages:
        failures.append(
            f"실제 스캔 PDF인데 OCR 처리 페이지가 부족함: "
            f"expected>={expected_pages}, actual={total_ocr}"
        )
    minimum_chars = 300 if not case.is_registry_case else 450
    if total_chars < minimum_chars:
        failures.append(f"그룹 추출 문자 수가 부족함: {total_chars}")
    return failures


def validate_lease_analysis(analysis: Any) -> list[str]:
    failures: list[str] = []
    for key in (
        "lessor_name", "lessee_name", "property_address",
        "deposit_amount", "contract_payment", "balance_payment",
        "contract_date", "move_in_date", "contract_start_date", "contract_end_date",
    ):
        if not available(field(analysis, key)):
            failures.append(f"계약서 필수 필드 미확인: {key}")

    for key, expected in {
        "deposit_amount": 150_000_000,
        "contract_payment": 8_000_000,
        "balance_payment": 142_000_000,
    }.items():
        actual = amount_value(field_value(analysis, key))
        if actual != expected:
            failures.append(f"계약서 금액 오류: {key}, expected={expected}, actual={actual}")

    for key, expected in {
        "contract_date": "2024-10-01",
        "move_in_date": "2024-11-28",
        "contract_start_date": "2024-11-28",
        "contract_end_date": "2026-11-27",
    }.items():
        actual = field_value(analysis, key)
        if actual != expected:
            failures.append(f"계약서 날짜 오류: {key}, expected={expected}, actual={actual!r}")

    if not owner_contains(field_value(analysis, "lessor_name"), "이오목"):
        failures.append(f"임대인 이름 오류: {field_value(analysis, 'lessor_name')!r}")
    if not owner_contains(field_value(analysis, "lessee_name"), "차금주"):
        failures.append(f"임차인 이름 오류: {field_value(analysis, 'lessee_name')!r}")

    address_text = compact(field_value(analysis, "property_address"))
    for token in ("마포구", "신공덕동", "201호"):
        if token not in address_text:
            failures.append(f"계약서 주소 핵심값 누락: {token}")
    return failures


def validate_registry_analysis(analysis: Any) -> list[str]:
    failures: list[str] = []
    for key in (
        "registry_address", "current_owners", "mortgage_exists",
        "active_restriction_exists", "trust_registration_exists",
    ):
        item = field(analysis, key)
        if item is None or item.status == AnalysisValueStatus.UNKNOWN:
            failures.append(f"등기부 필수 필드 미확인: {key}")

    if not owner_contains(field_value(analysis, "current_owners"), "이오목"):
        failures.append(f"현재 소유자 오류: {field_value(analysis, 'current_owners')!r}")

    address_text = compact(field_value(analysis, "registry_address"))
    for token in ("마포구", "신공덕동", "201호"):
        if token not in address_text:
            failures.append(f"등기부 주소 핵심값 누락: {token}")

    for key in (
        "mortgage_exists", "active_restriction_exists", "trust_registration_exists"
    ):
        actual = field_value(analysis, key)
        if actual is not False:
            failures.append(f"현재 유효 권리 오판: {key}, expected=False, actual={actual!r}")
    return failures


def validate_rag(result: Any, *, registry_case: bool) -> list[str]:
    failures: list[str] = []
    if result is None:
        return failures
    if not result.answer_ready:
        failures.append("최종 답변이 answer_ready가 아님")
    if result.document_analysis is None:
        failures.append("최종 결과에 document_analysis가 없음")
    if result.processing_status in {
        ChatbotProcessingStatus.RAG_EVIDENCE_NOT_FOUND,
        ChatbotProcessingStatus.RAG_SEARCH_FAILED,
        ChatbotProcessingStatus.RAG_GENERATION_FAILED,
        ChatbotProcessingStatus.RAG_VALIDATION_FAILED,
    }:
        failures.append(f"챗봇 실패 상태: {result.processing_status.value}")

    rag = result.consultation.rag_response
    evidence = getattr(rag.evidence_status, "value", rag.evidence_status)
    generation = getattr(rag.generation_status, "value", rag.generation_status)
    if evidence != EvidenceStatus.SUFFICIENT.value:
        failures.append(f"RAG 근거 상태가 sufficient가 아님: {evidence}")
    if generation not in {
        RAGGenerationStatus.COMPLETED.value,
        RAGGenerationStatus.PARTIAL_EVIDENCE.value,
    }:
        failures.append(f"RAG 생성 상태 실패: {generation}")
    if not rag.answer.immediate_actions:
        failures.append("지금 해야 할 행동이 비어 있음")
    if not rag.answer.references:
        failures.append("근거·참고 자료가 비어 있음")

    if registry_case:
        answer_text = compact(" ".join([
            rag.answer.core_judgment,
            *rag.answer.reasons,
            *rag.answer.immediate_actions,
            *rag.answer.hold_actions,
        ]))
        for phrase in (
            "현재근저당이있", "현재압류가있", "현재가압류가있", "현재신탁등기가있"
        ):
            if phrase in answer_text:
                failures.append(f"현재 유효 권리를 잘못 단정한 답변 문구: {phrase}")
    return failures


def build_cases(files: FileSet) -> tuple[EvaluationCase, ...]:
    return (
        EvaluationCase(
            evaluation_id="q21_lease_pdf",
            label="실제 계약서 PDF",
            documents=((files.lease_pdf, DocumentType.LEASE_CONTRACT),),
            question=(
                "실제 계약서 PDF를 첨부했습니다. 계약 당사자·주소·금액·날짜·특약을 "
                "확인하고 지금 해야 할 행동을 알려 주세요."
            ),
        ),
        EvaluationCase(
            evaluation_id="q22_registry_pdf",
            label="실제 계약서 PDF + 등기부등본 PDF 3장",
            documents=(
                (files.lease_pdf, DocumentType.LEASE_CONTRACT),
                *((path, DocumentType.REGISTRY) for path in files.registry_pdfs),
            ),
            question=(
                "같은 거래의 실제 계약서와 등기부등본 PDF를 첨부했습니다. 현재 유효한 "
                "권리관계와 계약서의 소유자·주소 일치 여부를 확인해 주세요."
            ),
        ),
    )


def main() -> None:
    args = parse_args()
    files = discover_files(args.downloads.expanduser().resolve(), args)

    if not args.local_only:
        if not os.getenv("OPENAI_API_KEY", "").strip():
            raise SystemExit("OPENAI_API_KEY가 없습니다. backend/.env를 확인하세요.")
        if not os.getenv("DATABASE_URL", "").strip():
            raise SystemExit("DATABASE_URL이 없습니다. backend/.env를 확인하세요.")

    print("=" * 116)
    print("Law 404 PDF 전용 최종 테스트 — 실제 계약서·등기부 상담")
    print("=" * 116)
    print(
        "실행 모드:",
        "업로드·OCR·분석·비교" if args.local_only
        else "업로드·OCR·분석·비교 + 실제 RAG 답변",
    )
    print_file_mapping(files)

    cases = build_cases(files)
    summary = Counter()

    with TemporaryDirectory(prefix="law404-pdf-final-") as temp_dir:
        store = MemoryConversationStore()
        conversation_service = APartConversationService(
            store=store,
            slot_extractor=NoopSlotExtractor(),
        )
        document_service = APartDocumentUploadService(
            conversation_service=conversation_service,
            storage_root=Path(temp_dir) / "storage",
        )
        chatbot_service = APartChatbotService(
            conversation_service=conversation_service,
            document_service=document_service,
        )

        for index, case in enumerate(cases, start=1):
            print()
            print("=" * 116)
            print(f"[{index}/2] {case.evaluation_id} — {case.label}")
            print("질문:", case.question)
            print("-" * 116)

            routed = route_issues(case.question)
            state = store.create(create_conversation_state(
                primary_issue_id=routed.primary_issue_id,
                related_issue_ids=list(routed.related_issue_ids),
            ))

            try:
                uploaded_ids: list[str] = []
                extraction_pairs: list[Any] = []
                for path, document_type in case.documents:
                    uploaded = document_service.upload_bytes(
                        conversation_id=state.conversation_id,
                        document_type=document_type,
                        filename=path_label(path),
                        content_type=content_type(path),
                        data=path.read_bytes(),
                    )
                    uploaded_ids.append(uploaded.document.document_id)
                    extracted = document_service.extract_document(
                        conversation_id=state.conversation_id,
                        document_id=uploaded.document.document_id,
                        force=True,
                    )
                    extraction_pairs.append((path, extracted.extraction))

                if args.local_only:
                    response = document_service.analyze_documents(
                        conversation_id=state.conversation_id,
                        document_ids=uploaded_ids,
                        force=False,
                    )
                    result = None
                else:
                    result = chatbot_service.handle(ChatbotTurnRequest(
                        question=case.question,
                        conversation_id=state.conversation_id,
                        document_ids=uploaded_ids,
                        analyze_documents=True,
                        force_document_analysis=False,
                    ))
                    response = result.document_analysis
                    if response is None:
                        raise AssertionError("document_analysis가 반환되지 않았습니다.")

                print_extractions(extraction_pairs)
                print_analysis(response)

                failures = validate_extractions(case, extraction_pairs)
                if not response.lease_analyses:
                    failures.append("계약서 분석 결과가 없음")
                else:
                    failures.extend(validate_lease_analysis(response.lease_analyses[-1]))

                if case.is_registry_case:
                    if not response.registry_analyses:
                        failures.append("등기부 분석 결과가 없음")
                    else:
                        failures.extend(validate_registry_analysis(response.registry_analyses[-1]))
                    if response.comparison is None:
                        failures.append("계약서·등기부 비교 결과가 없음")
                    else:
                        by_key = {item.key: item for item in response.comparison.comparisons}
                        for key in ("owner_lessor", "property_address"):
                            item = by_key.get(key)
                            if item is None:
                                failures.append(f"문서 비교 항목 누락: {key}")
                            elif item.status not in {
                                ComparisonStatus.MATCH,
                                ComparisonStatus.UNCERTAIN,
                            }:
                                failures.append(
                                    f"같은 거래 문서가 불일치로 판정됨: "
                                    f"{key}={item.status.value}"
                                )

                failures.extend(validate_rag(result, registry_case=case.is_registry_case))

                if result is not None:
                    print()
                    print("실제 사용자형 답변")
                    print(format_answer_for_console(result.consultation.rag_response))
                    print("챗봇 처리 상태:", result.processing_status.value)
                    print("answer_ready:", result.answer_ready)
                    print("전체 경고:", result.warnings)

                if failures:
                    summary["FAIL"] += 1
                    print("자동 평가 → FAIL")
                    for number, failure in enumerate(failures, start=1):
                        print(f"{number}. {failure}")
                else:
                    summary["PASS"] += 1
                    print("자동 평가 → PASS")

            except Exception as exc:
                summary["ERROR"] += 1
                print("자동 평가 → ERROR")
                print(f"{type(exc).__name__}: {exc}")

    print()
    print("=" * 116)
    print("PDF 전용 실제 문서 상담 평가 요약")
    print("-" * 116)
    print("PASS:", summary["PASS"])
    print("FAIL:", summary["FAIL"])
    print("ERROR:", summary["ERROR"])
    print("-" * 116)

    if summary["PASS"] != 2 or summary["FAIL"] != 0 or summary["ERROR"] != 0:
        print("PDF 최종 판정: FAIL")
        raise SystemExit(1)

    print("PDF 최종 판정: PASS")
    print("현재 누적: 자연어 20문항 PASS + 실제 PDF 2문항 PASS = 총 22문항 PASS")
    print("=" * 116)


if __name__ == "__main__":
    main()
