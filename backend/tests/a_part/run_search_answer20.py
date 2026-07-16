# backend/tests/a_part/run_search_answer20.py
# A part 대표 질문 20개로 검색·근거 선택·구조화 답변 품질을 평가한다.

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[3]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import app.llm.a_part as a_part_module
from app.rag.retrievers.a_part import CODE_VERSION as SEARCH_CODE_VERSION
from app.llm.a_part import (
    APartRAGResponse,
    ConsultationContext,
    EvidenceStatus,
    RISK_LEVELS,
    answer_with_rag,
    format_answer_for_console,
)




KeywordGroup = tuple[str, ...]


@dataclass(frozen=True)
class EvalCase:
    question_id: str
    question: str
    description: str
    context: ConsultationContext

    required_text_groups: tuple[KeywordGroup, ...] = ()
    required_hold_groups: tuple[KeywordGroup, ...] = ()
    reference_groups: tuple[KeywordGroup, ...] = ()

    banned_phrases: tuple[str, ...] = ()
    disallowed_risk_levels: tuple[str, ...] = ()

    search_top_k: int = 15
    answer_evidence_count: int = 5
    min_similarity: float = 0.30
    candidate_k: int = 80


@dataclass
class EvalResult:
    question_id: str
    status: str
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _group_description(group: KeywordGroup) -> str:
    return " / ".join(group)


def _answer_text(response: APartRAGResponse) -> str:
    answer = response.answer
    values = [
        answer.risk_level,
        answer.core_judgment,
        *answer.immediate_actions,
        *answer.hold_actions,
        *answer.reasons,
        *answer.required_information,
        *answer.follow_up_questions,
    ]

    if answer.confirmation_message:
        values.append(answer.confirmation_message)

    return " ".join(values)


def _reference_text(response: APartRAGResponse) -> str:
    values: list[str] = []

    for reference in response.answer.references:
        values.extend(
            [
                reference.title,
                reference.collection,
                reference.source_type or "",
                reference.issue_id or "",
                reference.text_preview,
            ]
        )

    return " ".join(values)


def _validate_common(response: APartRAGResponse) -> list[str]:
    failures: list[str] = []
    answer = response.answer
    answer_text = _answer_text(response)

    expected_version = getattr(
        a_part_module,
        "ANSWER_CODE_VERSION",
        None,
    )

    if response.answer_code_version != expected_version:
        failures.append(
            "응답의 답변 코드 버전과 실제 import된 코드 버전이 다름"
        )

    if response.search_code_version != SEARCH_CODE_VERSION:
        failures.append(
            "응답의 검색 코드 버전과 실제 import된 코드 버전이 다름: "
            f"response={response.search_code_version}, "
            f"imported={SEARCH_CODE_VERSION}"
        )

    if answer.risk_level not in RISK_LEVELS:
        failures.append(
            f"허용되지 않은 위험 수준: {answer.risk_level}"
        )

    if not answer.core_judgment.strip():
        failures.append("핵심 판단이 비어 있음")

    if not answer.immediate_actions:
        failures.append("지금 해야 할 행동이 비어 있음")

    if len(answer.immediate_actions) > 3:
        failures.append("지금 해야 할 행동이 3개를 초과함")

    if len(answer.hold_actions) > 3:
        failures.append("보류 행동이 3개를 초과함")

    if len(answer.follow_up_questions) > 3:
        failures.append("추가 질문이 3개를 초과함")

    common_banned_phrases = [
        "이 계약은 안전합니다",
        "이 계약은 사기입니다",
        "사기가 확실합니다",
        "무조건 계약해도 됩니다",
        "무조건 송금해도 됩니다",
        "소송에서 반드시 이깁니다",
        "보증보험에 반드시 가입됩니다",
    ]

    for phrase in common_banned_phrases:
        if phrase in answer_text:
            failures.append(
                f"서비스 금지 단정 표현 포함: {phrase}"
            )

    for reference in answer.references:
        if not reference.document_id:
            failures.append(
                "법률 근거·참고 자료의 document_id가 비어 있음"
            )
        if not reference.text_preview:
            failures.append(
                "법률 근거·참고 자료의 text_preview가 비어 있음: "
                f"{reference.title}"
            )

    return failures


def _validate_case(
    case: EvalCase,
    response: APartRAGResponse,
) -> EvalResult:
    failures = _validate_common(response)
    warnings: list[str] = []

    answer = response.answer
    answer_text = _answer_text(response)
    hold_text = " ".join(answer.hold_actions)
    reference_text = _reference_text(response)

    if answer.risk_level in case.disallowed_risk_levels:
        failures.append(
            "현재 상황에 맞지 않는 위험 수준: "
            f"{answer.risk_level}"
        )

    for group in case.required_text_groups:
        if not _contains_any(answer_text, group):
            failures.append(
                "답변 필수 내용 누락: "
                f"{_group_description(group)}"
            )

    for group in case.required_hold_groups:
        if not _contains_any(hold_text, group):
            failures.append(
                "보류 행동 누락: "
                f"{_group_description(group)}"
            )

    for phrase in case.banned_phrases:
        if phrase in answer_text:
            failures.append(
                f"질문별 금지 단정 표현 포함: {phrase}"
            )

    missing_reference_groups = [
        group
        for group in case.reference_groups
        if not _contains_any(reference_text, group)
    ]

    if response.evidence_status == EvidenceStatus.SUFFICIENT:
        if not answer.references:
            warnings.append(
                "근거 상태가 sufficient인데 표시된 참고 자료가 없음"
            )

        if missing_reference_groups:
            warnings.append(
                "sufficient로 분류됐지만 참고 자료가 질문 핵심과 "
                "완전히 맞지 않음: "
                + ", ".join(
                    _group_description(group)
                    for group in missing_reference_groups
                )
            )

    elif response.evidence_status == EvidenceStatus.PARTIAL:
        warnings.append(
            "직접 근거가 일부만 확인되어 답변 내용과 참고 자료를 검토해야 함"
        )

        if missing_reference_groups and answer.references:
            warnings.append(
                "partial 참고 자료에서 질문 핵심 근거가 부족함: "
                + ", ".join(
                    _group_description(group)
                    for group in missing_reference_groups
                )
            )

    else:
        warnings.append(
            "직접 근거가 부족하므로 데이터 또는 검색 기준 검토가 필요함"
        )

    if failures:
        status = "FAIL"
    elif warnings:
        status = "REVIEW"
    else:
        status = "PASS"

    return EvalResult(
        question_id=case.question_id,
        status=status,
        failures=failures,
        warnings=warnings,
    )


EVAL_CASES: tuple[EvalCase, ...] = (
    EvalCase(
        question_id="q01_owner_proxy",
        question=(
            "집주인 아들이 대신 계약하러 왔는데 "
            "위임장 없이 계약해도 되나요?"
        ),
        description=(
            "실제 소유자의 대리 의사·위임 범위·계약금 수령 권한과 "
            "서명·송금 보류를 확인"
        ),
        context=ConsultationContext(
            contract_stage="계약서 작성 전",
            payment_status="아직 송금 전",
            contract_type="전세",
            known_facts=[
                "실제 소유자가 아닌 집주인의 아들이 계약을 진행하려고 함",
                "현재 위임장 보유 여부는 확인되지 않음",
            ],
        ),
        required_text_groups=(
            ("소유자", "집주인 본인"),
            ("대리", "위임"),
            ("계좌", "수령 권한"),
        ),
        required_hold_groups=(
            ("서명", "계약서"),
            ("송금", "계약금", "잔금"),
        ),
        reference_groups=(
            ("위임장", "대리권", "위임 범위", "수령 권한"),
        ),
        disallowed_risk_levels=(
            "현재 입력 기준 중대한 보류 사유 미확인",
            "확인 필요",
        ),
    ),
    EvalCase(
        question_id="q02_co_owner",
        question=(
            "공동명의 집인데 소유자 한 명만 나와서 "
            "계약해도 되나요?"
        ),
        description=(
            "공동소유자 범위와 다른 소유자의 동의·대리 권한을 "
            "확인하기 전 계약 진행을 보류하는지 확인"
        ),
        context=ConsultationContext(
            contract_stage="계약서 작성 전",
            payment_status="아직 송금 전",
            contract_type="전세",
            known_facts=[
                "등기부등본상 소유자가 두 명임",
                "계약 현장에는 공동소유자 한 명만 나옴",
                "다른 공동소유자의 동의 자료는 확인되지 않음",
            ],
        ),
        required_text_groups=(
            ("공동명의", "공동소유자"),
            ("동의", "대리 권한", "위임"),
            ("등기부등본", "소유자"),
        ),
        required_hold_groups=(
            ("서명", "계약 진행"),
            ("송금", "계약금"),
        ),
        reference_groups=(
            ("공동소유", "공동명의", "동의", "대리권"),
        ),
        disallowed_risk_levels=(
            "현재 입력 기준 중대한 보류 사유 미확인",
        ),
    ),
    EvalCase(
        question_id="q03_owner_lessor_mismatch",
        question=(
            "등기부등본 소유자랑 계약서 임대인 이름이 "
            "다른데 괜찮나요?"
        ),
        description=(
            "소유자와 임대인 불일치 원인·권한을 확인하기 전 "
            "서명과 지급을 보류하는지 확인"
        ),
        context=ConsultationContext(
            contract_stage="계약서 작성 전",
            payment_status="아직 송금 전",
            contract_type="전세",
            known_facts=[
                "등기부등본 소유자와 계약서상 임대인 이름이 다름",
                "두 사람의 관계와 계약 권한은 확인되지 않음",
            ],
        ),
        required_text_groups=(
            ("등기부등본", "소유자"),
            ("임대인", "계약 상대방"),
            ("권한", "위임", "관계"),
        ),
        required_hold_groups=(
            ("서명", "계약 진행"),
            ("송금", "계약금"),
        ),
        reference_groups=(
            ("소유자", "임대인", "대리", "위임"),
        ),
        disallowed_risk_levels=(
            "현재 입력 기준 중대한 보류 사유 미확인",
        ),
    ),
    EvalCase(
        question_id="q04_broker_account_payment",
        question="부동산 계좌로 계약금을 보내라고 하는데 괜찮나요?",
        description=(
            "예금주·실제 소유자·계약금 수령 권한을 확인하기 전 "
            "송금을 보류하는지 확인"
        ),
        context=ConsultationContext(
            contract_stage="오늘 계약금·계약서 진행 예정",
            payment_status="아직 송금 전",
            contract_type="전세",
            known_facts=[
                "계약금을 부동산 명의 계좌로 보내 달라는 요청을 받음",
                "해당 계좌의 계약금 수령 권한은 확인되지 않음",
            ],
        ),
        required_text_groups=(
            ("예금주", "계좌 명의"),
            ("소유자", "임대인", "계약 상대방"),
            ("수령 권한", "지급 근거"),
        ),
        required_hold_groups=(
            ("송금", "계약금", "이체"),
        ),
        reference_groups=(
            ("예금주", "수령 권한", "제3자 계좌", "계약금 송금"),
        ),
        disallowed_risk_levels=(
            "현재 입력 기준 중대한 보류 사유 미확인",
            "확인 필요",
        ),
    ),
    EvalCase(
        question_id="q05_account_change_before_contract",
        question=(
            "계약 직전에 계좌가 바뀌었다고 하는데 "
            "어떻게 확인해야 하나요?"
        ),
        description=(
            "갑작스러운 계좌 변경 시 소유자 본인 확인과 "
            "변경 근거 확인 전 송금을 보류하는지 확인"
        ),
        context=ConsultationContext(
            contract_stage="계약금 송금 직전",
            payment_status="아직 송금 전",
            contract_type="전세",
            known_facts=[
                "안내받았던 계약금 계좌가 계약 직전에 변경됨",
                "변경 요청이 실제 소유자의 의사인지 확인되지 않음",
            ],
        ),
        required_text_groups=(
            ("계좌 변경", "바뀐 계좌", "변경 요청"),
            ("소유자 본인", "임대인 본인"),
            ("예금주", "수령 권한", "변경 근거"),
        ),
        required_hold_groups=(
            ("송금", "계약금", "이체"),
        ),
        reference_groups=(
            ("계좌 변경", "예금주", "수령 권한", "계약금"),
        ),
        disallowed_risk_levels=(
            "현재 입력 기준 중대한 보류 사유 미확인",
        ),
    ),
    EvalCase(
        question_id="q06_broker_explanation_mismatch",
        question=(
            "중개대상물 확인설명서 내용이 계약서랑 다르면 "
            "어떻게 봐야 하나요?"
        ),
        description=(
            "두 문서의 불일치 항목을 대조하고 정정·설명 전 "
            "서명을 보류하는지 확인"
        ),
        context=ConsultationContext(
            contract_stage="계약서 서명 전",
            payment_status="아직 송금 전",
            contract_type="전세",
            known_facts=[
                "중개대상물 확인설명서와 계약서 일부 내용이 다름",
                "어떤 문서가 정확한지 설명받지 못함",
            ],
        ),
        required_text_groups=(
            ("확인설명서", "중개대상물"),
            ("계약서",),
            ("불일치", "다른 내용", "대조"),
            ("정정", "설명", "확인"),
        ),
        required_hold_groups=(
            ("서명", "계약 진행"),
        ),
        reference_groups=(
            ("중개대상물 확인설명서", "확인·설명", "공인중개사"),
        ),
        disallowed_risk_levels=(
            "현재 입력 기준 중대한 보류 사유 미확인",
        ),
    ),
    EvalCase(
        question_id="q07_mortgage",
        question="등기부등본에 근저당이 있는데 전세계약해도 되나요?",
        description=(
            "근저당 존재만으로 계약 가능 여부를 단정하지 않고 "
            "채권최고액·보증금·주택가액을 함께 확인하는지 평가"
        ),
        context=ConsultationContext(
            contract_stage="계약서 작성 전",
            payment_status="아직 송금 전",
            contract_type="전세",
            known_facts=[
                "등기부등본에 근저당권이 표시되어 있음",
                "채권최고액과 실제 채무액, 주택가액은 아직 확인하지 않음",
            ],
        ),
        required_text_groups=(
            ("근저당", "저당권"),
            ("채권최고액", "채무액"),
            ("보증금",),
            ("주택 가격", "주택가액", "시세"),
        ),
        required_hold_groups=(
            ("서명", "계약 진행", "송금"),
        ),
        reference_groups=(
            ("근저당", "저당권", "채권최고액"),
            ("보증금", "주택", "임대차"),
        ),
        banned_phrases=(
            "근저당이 있으면 계약할 수 없습니다",
            "근저당이 있어도 안전합니다",
        ),
        disallowed_risk_levels=(
            "현재 입력 기준 중대한 보류 사유 미확인",
            "확인 필요",
        ),
    ),
    EvalCase(
        question_id="q08_multiunit_priority",
        question="다가구주택인데 선순위 보증금이 많으면 위험한가요?",
        description=(
            "다가구 전체 선순위 보증금·권리관계·주택가액을 "
            "함께 확인하도록 안내하는지 평가"
        ),
        context=ConsultationContext(
            contract_stage="계약서 작성 전",
            payment_status="아직 송금 전",
            contract_type="전세",
            known_facts=[
                "다가구주택 계약을 검토 중임",
                "다른 세대의 선순위 보증금 총액은 확인하지 못함",
            ],
        ),
        required_text_groups=(
            ("다가구",),
            ("선순위 보증금", "선순위 임차인"),
            ("주택 가격", "주택가액", "시세"),
            ("등기부등본", "권리관계"),
        ),
        required_hold_groups=(
            ("서명", "계약 진행", "송금"),
        ),
        reference_groups=(
            ("다가구", "선순위 보증금", "우선변제"),
        ),
        disallowed_risk_levels=(
            "현재 입력 기준 중대한 보류 사유 미확인",
            "확인 필요",
        ),
    ),
    EvalCase(
        question_id="q09_registry_restriction_warning",
        question=(
            "등기부등본에 압류, 가압류 같은 권리 제한이 있으면 "
            "계약 전에 어떻게 확인해야 하나요?"
        ),
        description=(
            "압류 법리를 깊게 단정하지 않고 등기부 위험 신호로 "
            "처리해 확인·보류 행동을 안내하는지 평가"
        ),
        context=ConsultationContext(
            contract_stage="계약서 작성 전",
            payment_status="아직 송금 전",
            contract_type="전세",
            known_facts=[
                "등기부등본에서 압류 또는 가압류 표시를 확인함",
                "말소 여부와 현재 효력은 확인되지 않음",
            ],
        ),
        required_text_groups=(
            ("압류", "가압류", "권리 제한"),
            ("등기부등본", "권리관계"),
            ("말소", "해소 계획", "현재 효력"),
        ),
        required_hold_groups=(
            ("서명", "계약 진행"),
            ("송금", "계약금", "잔금"),
        ),
        reference_groups=(
            ("압류", "가압류", "가처분", "가등기"),
            ("부동산", "주택", "임대차", "등기", "보증금", "경매"),
        ),
        banned_phrases=(
            "압류가 있으면 계약은 무효",
            "가압류가 있으면 계약은 무효",
        ),
        disallowed_risk_levels=(
            "현재 입력 기준 중대한 보류 사유 미확인",
            "확인 필요",
        ),
    ),
    EvalCase(
        question_id="q10_trust",
        question="신탁등기가 있는 집인데 임대인이랑 바로 계약해도 되나요?",
        description=(
            "신탁원부·수탁자·임대 권한·동의 조건을 확인하기 전 "
            "계약과 송금을 보류하는지 평가"
        ),
        context=ConsultationContext(
            contract_stage="계약서 작성 전",
            payment_status="아직 송금 전",
            contract_type="전세",
            known_facts=[
                "등기부등본에 신탁등기가 표시되어 있음",
                "계약 상대방의 임대 권한과 신탁원부 내용은 확인하지 않음",
            ],
        ),
        required_text_groups=(
            ("신탁등기", "신탁"),
            ("신탁원부",),
            ("수탁자", "임대 권한", "동의"),
        ),
        required_hold_groups=(
            ("서명", "계약 진행"),
            ("송금", "계약금"),
        ),
        reference_groups=(
            ("신탁등기", "신탁원부", "수탁자"),
        ),
        disallowed_risk_levels=(
            "현재 입력 기준 중대한 보류 사유 미확인",
            "확인 필요",
        ),
    ),
    EvalCase(
        question_id="q11_opposability_move_in",
        question="전입신고를 하면 대항력이 언제 생기나요?",
        description=(
            "주택 인도와 주민등록을 함께 갖춘 시점 및 "
            "다음 날 효력 발생 원칙을 설명하는지 평가"
        ),
        context=ConsultationContext(
            contract_stage="계약서를 작성한 뒤 입주 준비 중",
            payment_status="계약금 지급함",
            contract_type="전세",
            known_facts=[
                "아직 실제 입주와 전입신고 전임",
            ],
        ),
        required_text_groups=(
            ("주택 인도", "실제 입주", "인도"),
            ("전입신고", "주민등록"),
            ("다음 날", "익일"),
            ("대항력",),
        ),
        reference_groups=(
            ("주택의 인도", "주민등록", "전입신고"),
            ("다음 날", "대항력"),
        ),
        banned_phrases=(
            "전입신고 즉시 대항력이 생깁니다",
            "전입신고만 하면 대항력이 생깁니다",
        ),
        disallowed_risk_levels=(
            "고위험 대응 전환 검토",
        ),
    ),
    EvalCase(
        question_id="q12_fixed_date_priority",
        question="확정일자를 받으면 우선변제권이 생기나요?",
        description=(
            "확정일자만으로 충분하다고 단정하지 않고 "
            "대항요건과 우선변제권의 관계를 설명하는지 평가"
        ),
        context=ConsultationContext(
            contract_stage="계약서를 작성한 뒤 입주 준비 중",
            payment_status="계약금 지급함",
            contract_type="전세",
            known_facts=[
                "확정일자 신청을 검토 중임",
                "아직 입주와 전입신고 전임",
            ],
        ),
        required_text_groups=(
            ("확정일자",),
            ("주택 인도", "입주"),
            ("전입신고", "주민등록", "대항요건"),
            ("우선변제권",),
        ),
        reference_groups=(
            ("확정일자",),
            ("우선변제권", "대항요건"),
        ),
        banned_phrases=(
            "확정일자만 받으면 우선변제권이 생깁니다",
            "확정일자를 받는 즉시 우선변제권이 생깁니다",
        ),
        disallowed_risk_levels=(
            "고위험 대응 전환 검토",
        ),
    ),
    EvalCase(
        question_id="q13_owner_change",
        question=(
            "계약 후 집주인이 바뀌었다고 하는데 "
            "제 보증금은 어떻게 되나요?"
        ),
        description=(
            "소유자 변경 시 대항력 요건·새 소유자·보증금 반환 관계를 "
            "확인하도록 안내하는지 평가"
        ),
        context=ConsultationContext(
            contract_stage="계약 후 거주 중",
            payment_status="보증금 지급 완료",
            contract_type="전세",
            known_facts=[
                "계약 후 주택 소유자가 변경됐다는 안내를 받음",
                "현재 등기부등본과 새 소유자 정보는 확인하지 않음",
            ],
        ),
        required_text_groups=(
            ("소유자 변경", "집주인이 바뀌", "새 소유자"),
            ("대항력", "전입신고", "주택 인도"),
            ("보증금 반환", "보증금"),
            ("등기부등본", "소유자 확인"),
        ),
        reference_groups=(
            ("소유자", "양수인", "임대인 지위"),
            ("대항력", "보증금"),
        ),
        banned_phrases=(
            "새 집주인이 무조건 보증금을 반환해야 합니다",
            "보증금을 받을 수 없습니다",
        ),
    ),
    EvalCase(
        question_id="q14_special_clause_deposit_return",
        question=(
            "계약서 특약이나 계약금 반환 조건은 "
            "어떻게 확인해야 하나요?"
        ),
        description=(
            "특약의 정확한 문구·발동 조건·반환 범위·증빙을 "
            "확인하도록 안내하는지 평가"
        ),
        context=ConsultationContext(
            contract_stage="계약서 서명 전",
            payment_status="아직 송금 전",
            contract_type="전세",
            known_facts=[
                "계약금 반환과 관련된 특약 문구가 모호함",
                "어떤 상황에서 반환되는지 명확히 설명받지 못함",
            ],
        ),
        required_text_groups=(
            ("특약",),
            ("계약금 반환", "반환 조건"),
            ("조건", "사유", "기한"),
            ("서면", "문구", "기록"),
        ),
        required_hold_groups=(
            ("서명", "계약 진행", "송금"),
        ),
        reference_groups=(
            ("특약", "계약금", "해제", "반환"),
        ),
        banned_phrases=(
            "특약이 있으면 무조건 계약금을 돌려받습니다",
        ),
        disallowed_risk_levels=(
            "현재 입력 기준 중대한 보류 사유 미확인",
        ),
    ),
    EvalCase(
        question_id="q15_after_contract_procedure",
        question="계약서 쓴 직후에 바로 해야 할 절차가 뭐예요?",
        description=(
            "계약서·지급 기록 보관, 잔금 전 권리관계 재확인, "
            "임대차신고·전입신고·확정일자 준비를 평가"
        ),
        context=ConsultationContext(
            contract_stage="계약서를 작성한 뒤 잔금 전",
            payment_status="계약금 지급함",
            contract_type="전세",
            known_facts=[
                "계약서 작성과 계약금 지급을 마침",
                "아직 잔금과 실제 입주 전임",
            ],
        ),
        required_text_groups=(
            ("계약서 원본", "계약서 보관", "계약서"),
            ("이체 내역", "영수증", "지급 기록"),
            ("등기부등본", "권리관계"),
            ("전입신고",),
            ("확정일자",),
            ("임대차신고", "주택 임대차신고"),
        ),
        reference_groups=(
            ("확정일자", "전입신고", "대항력"),
            ("임대차신고", "계약 후", "권리관계"),
        ),
        disallowed_risk_levels=(
            "고위험 대응 전환 검토",
            "진행 보류 권장",
        ),
    ),
    EvalCase(
        question_id="q16_lease_report",
        question="주택 임대차신고는 꼭 해야 하나요?",
        description=(
            "모든 계약에 무조건 적용된다고 단정하지 않고 "
            "신고 대상·기한·공식 확인 방법을 안내하는지 평가"
        ),
        context=ConsultationContext(
            contract_stage="계약서를 작성한 뒤",
            payment_status="계약금 지급함",
            contract_type="전세",
            known_facts=[
                "주택 임대차신고 대상 여부를 확인하지 못함",
            ],
        ),
        required_text_groups=(
            ("임대차신고", "주택 임대차신고"),
            ("신고 대상", "대상 여부"),
            ("기한", "30일"),
            ("공식", "주민센터", "신고 시스템"),
        ),
        reference_groups=(
            ("주택 임대차계약신고", "임대차신고"),
            ("신고", "계약체결일"),
        ),
        banned_phrases=(
            "모든 임대차계약은 무조건 신고해야 합니다",
            "신고하지 않아도 됩니다",
        ),
        disallowed_risk_levels=(
            "고위험 대응 전환 검토",
        ),
    ),
    EvalCase(
        question_id="q17_household_certificate",
        question="전입세대확인서는 언제 확인해야 하나요?",
        description=(
            "계약 전과 잔금 전의 확인 시점, 기존 전입세대와 "
            "선순위 위험 확인 목적을 설명하는지 평가"
        ),
        context=ConsultationContext(
            contract_stage="계약서 작성 전",
            payment_status="아직 송금 전",
            contract_type="전세",
            known_facts=[
                "전입세대확인서를 아직 확인하지 않음",
            ],
        ),
        required_text_groups=(
            ("전입세대확인서", "전입세대"),
            ("계약 전",),
            ("잔금 전", "잔금 지급 전"),
            ("선순위", "기존 전입", "점유"),
        ),
        reference_groups=(
            ("전입세대", "전입세대확인서", "열람"),
            ("계약 전", "잔금 전", "선순위"),
        ),
        disallowed_risk_levels=(
            "고위험 대응 전환 검토",
        ),
    ),
    EvalCase(
        question_id="q18_address_mismatch",
        question=(
            "계약서 주소와 등기부등본 주소가 조금 다른데 "
            "어떻게 봐야 하나요?"
        ),
        description=(
            "주소 불일치를 단순 오기로 넘기지 않고 동·호수·지번·"
            "도로명과 실제 목적물을 대조하는지 평가"
        ),
        context=ConsultationContext(
            contract_stage="계약서 서명 전",
            payment_status="아직 송금 전",
            contract_type="전세",
            known_facts=[
                "계약서 주소와 등기부등본 주소 표기가 일부 다름",
                "같은 목적물인지 아직 확인하지 못함",
            ],
        ),
        required_text_groups=(
            ("계약서 주소", "주소"),
            ("등기부등본",),
            ("지번", "도로명", "동·호수", "동호수", "건물명"),
            ("같은 목적물", "일치 여부"),
        ),
        required_hold_groups=(
            ("서명", "계약 진행"),
            ("송금", "계약금"),
        ),
        reference_groups=(
            ("주소", "소재지", "목적물"),
            ("등기부등본", "계약서"),
        ),
        disallowed_risk_levels=(
            "현재 입력 기준 중대한 보류 사유 미확인",
        ),
    ),
    EvalCase(
        question_id="q19_deposit_transfer_mismatch",
        question=(
            "계약서 보증금이랑 이체 내역 금액이 다르면 "
            "어떻게 해야 하나요?"
        ),
        description=(
            "계약서 금액·실제 이체액·지급 일자·수령인을 대조하고 "
            "추가 지급 전 정정하도록 안내하는지 평가"
        ),
        context=ConsultationContext(
            contract_stage="계약서를 작성한 뒤 잔금 전",
            payment_status="일부 금액 지급함",
            contract_type="전세",
            known_facts=[
                "계약서에 적힌 보증금과 현재 이체 내역 합계가 다름",
                "차액의 원인과 수령 확인은 정리되지 않음",
            ],
        ),
        required_text_groups=(
            ("계약서",),
            ("보증금",),
            ("이체 내역", "송금 내역", "지급 내역"),
            ("차액", "금액 불일치", "합계"),
            ("영수증", "수령 확인", "정정"),
        ),
        required_hold_groups=(
            ("추가 송금", "추가 지급", "잔금"),
        ),
        reference_groups=(
            ("계약서", "보증금"),
            ("이체 내역", "지급 증빙", "영수증"),
        ),
        disallowed_risk_levels=(
            "현재 입력 기준 중대한 보류 사유 미확인",
        ),
    ),
    EvalCase(
        question_id="q20_guarantee_check",
        question="전세보증금반환보증 가입 전에 뭘 확인해야 하나요?",
        description=(
            "가입 가능 여부를 단정하지 않고 공식 상품안내·심사 조건·"
            "계약과 권리관계·제출 서류를 안내하는지 평가"
        ),
        context=ConsultationContext(
            contract_stage="계약서를 작성한 뒤 잔금 전",
            payment_status="계약금 지급함",
            contract_type="전세",
            known_facts=[
                "전세보증금반환보증 가입을 검토 중임",
                "보증기관의 공식 심사는 아직 받지 않음",
            ],
        ),
        required_text_groups=(
            ("보증기관",),
            ("심사",),
            ("가입 대상", "신청 가능 기간", "보증 한도"),
            ("계약서", "임대차계약서"),
            ("등기부등본", "권리관계"),
            ("제출 서류", "지급 증빙"),
        ),
        reference_groups=(
            ("전세보증금반환보증", "반환보증"),
            ("신청절차", "서류제출", "심사", "보증서 발급"),
        ),
        banned_phrases=(
            "보증보험 가입 가능합니다",
            "보증보험에 가입할 수 있습니다",
            "보증보험 가입이 불가능합니다",
            "보증보험에 가입할 수 없습니다",
            "반드시 가입됩니다",
        ),
        disallowed_risk_levels=(
            "고위험 대응 전환 검토",
            "진행 보류 권장",
        ),
    ),
)


def _serialize_case(
    case: EvalCase,
    response: APartRAGResponse,
    result: EvalResult,
) -> dict:
    return {
        "question_id": case.question_id,
        "question": case.question,
        "description": case.description,
        "status": result.status,
        "failures": result.failures,
        "warnings": result.warnings,
        "response": response.model_dump(mode="json"),
    }


def _print_compact_result(
    response: APartRAGResponse,
    result: EvalResult,
) -> None:
    answer = response.answer

    print(f"자동 평가: {result.status}")
    print(f"근거 상태: {response.evidence_status.value}")
    print(f"위험 수준: {answer.risk_level}")
    print(f"핵심 판단: {answer.core_judgment}")

    if answer.hold_actions:
        print("보류 행동:")
        for index, item in enumerate(
            answer.hold_actions,
            start=1,
        ):
            print(f"  {index}. {item}")
    else:
        print("보류 행동: 없음")

    print(f"참고 자료 수: {len(answer.references)}개")

    if result.failures:
        print("실패 이유:")
        for index, item in enumerate(
            result.failures,
            start=1,
        ):
            print(f"  {index}. {item}")

    if result.warnings:
        print("검토 메모:")
        for index, item in enumerate(
            result.warnings,
            start=1,
        ):
            print(f"  {index}. {item}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="A part 구조화 답변 대표 질문 20개 평가",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="각 질문의 전체 구조화 답변과 참고 근거를 출력합니다.",
    )
    parser.add_argument(
        "--only",
        nargs="*",
        default=None,
        help=(
            "특정 질문 ID만 실행합니다. "
            "예: --only q07_mortgage q10_trust"
        ),
    )
    return parser.parse_args()


def run_evaluation(
    *,
    full: bool = False,
    only: list[str] | None = None,
) -> dict:
    """대표 질문을 실행하고 파일 저장 없이 평가 결과를 반환한다."""
    selected_cases = list(EVAL_CASES)

    if only:
        only_ids = set(only)
        selected_cases = [
            case
            for case in EVAL_CASES
            if case.question_id in only_ids
        ]

        unknown_ids = only_ids - {
            case.question_id
            for case in EVAL_CASES
        }

        if unknown_ids:
            raise ValueError(
                "등록되지 않은 질문 ID: "
                + ", ".join(sorted(unknown_ids))
            )

    print(
        "실제 import 파일:",
        Path(a_part_module.__file__).resolve(),
    )
    print(
        "불러온 답변 코드 버전:",
        getattr(
            a_part_module,
            "ANSWER_CODE_VERSION",
            "버전 정보 없음",
        ),
    )
    print("평가 질문 수:", len(selected_cases))

    summary = {
        "PASS": 0,
        "REVIEW": 0,
        "FAIL": 0,
        "ERROR": 0,
    }
    serialized_results: list[dict] = []

    for case_index, case in enumerate(
        selected_cases,
        start=1,
    ):
        print()
        print("=" * 100)
        print(
            f"[{case_index}/{len(selected_cases)}] "
            f"{case.question_id}"
        )
        print("질문:", case.question)
        print("평가 목적:", case.description)
        print("-" * 100)

        try:
            response = answer_with_rag(
                query=case.question,
                consultation_context=case.context,
                search_top_k=case.search_top_k,
                answer_evidence_count=case.answer_evidence_count,
                min_similarity=case.min_similarity,
                candidate_k=case.candidate_k,
            )

            result = _validate_case(
                case=case,
                response=response,
            )
            summary[result.status] += 1

            if full:
                print(format_answer_for_console(response))
                print()
                print("자동 평가")
                print(f"→ {result.status}")

                if result.failures:
                    print("실패 이유")
                    for index, item in enumerate(
                        result.failures,
                        start=1,
                    ):
                        print(f"{index}. {item}")

                if result.warnings:
                    print("검토 메모")
                    for index, item in enumerate(
                        result.warnings,
                        start=1,
                    ):
                        print(f"{index}. {item}")
            else:
                _print_compact_result(
                    response=response,
                    result=result,
                )

            serialized_results.append(
                _serialize_case(
                    case=case,
                    response=response,
                    result=result,
                )
            )

        except Exception as error:
            summary["ERROR"] += 1
            print("자동 평가: ERROR")
            print("오류:", repr(error))

            serialized_results.append(
                {
                    "question_id": case.question_id,
                    "question": case.question,
                    "description": case.description,
                    "status": "ERROR",
                    "failures": [repr(error)],
                    "warnings": [],
                    "response": None,
                }
            )

    print()
    print("=" * 100)
    print("대표 질문 답변 평가 요약")
    print("-" * 100)
    for status in ["PASS", "REVIEW", "FAIL", "ERROR"]:
        print(f"{status}: {summary[status]}개")

    return {
        "answer_code_version": getattr(
            a_part_module,
            "ANSWER_CODE_VERSION",
            None,
        ),
        "search_code_version": SEARCH_CODE_VERSION,
        "question_count": len(selected_cases),
        "summary": summary,
        "results": serialized_results,
    }


def main() -> None:
    args = _parse_args()
    result = run_evaluation(
        full=args.full,
        only=args.only,
    )
    expected = {"PASS": len(result["results"]), "REVIEW": 0, "FAIL": 0, "ERROR": 0}
    if result.get("summary") != expected:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
