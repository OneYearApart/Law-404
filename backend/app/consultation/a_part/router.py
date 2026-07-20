"""첫 질문을 q01~q20 상담 issue로 연결한다."""

from __future__ import annotations

from dataclasses import dataclass

from app.consultation.a_part.issues import get_issue_definition


class UnsupportedConsultationIssueError(ValueError):
    """현재 q01~q20 범위로 분류하지 못한 질문."""


@dataclass(frozen=True, slots=True)
class RoutedIssues:
    primary_issue_id: str
    related_issue_ids: tuple[str, ...] = ()


RELATED_KEYWORDS: dict[str, tuple[str, ...]] = {
    "q01_owner_proxy": ("대리", "위임장", "대신 계약", "집주인 아들"),
    "q02_co_owner": ("공동명의", "공동소유", "소유자 한 명"),
    "q03_owner_lessor_mismatch": ("소유자와 임대인", "임대인 이름이 다", "소유자 이름이 다"),
    "q04_broker_account_payment": ("부동산 계좌", "중개사 계좌", "제3자 계좌"),
    "q05_account_change_before_contract": ("계좌 변경", "계좌가 바뀌", "새 계좌"),
    "q06_broker_explanation_mismatch": ("확인설명서", "중개대상물"),
    "q07_mortgage": ("근저당", "채권최고액", "저당권"),
    "q08_multiunit_priority": ("다가구", "선순위 보증금", "선순위 임차인"),
    "q09_registry_restriction_warning": ("압류", "가압류", "가처분", "가등기", "권리 제한"),
    "q10_trust": ("신탁등기", "신탁원부", "수탁자"),
    "q11_opposability_move_in": ("대항력", "전입신고"),
    "q12_fixed_date_priority": ("확정일자", "우선변제권"),
    "q13_owner_change": ("집주인이 바뀌", "소유자가 바뀌", "새 소유자"),
    "q14_special_clause_deposit_return": ("계약금 반환", "반환 특약", "반환 조건"),
    "q15_after_contract_procedure": ("계약 직후", "계약서 쓴 뒤", "바로 해야 할 절차"),
    "q16_lease_report": ("임대차신고", "임대차 신고"),
    "q17_household_certificate": ("전입세대확인서", "전입세대 확인서", "전입세대열람"),
    "q18_address_mismatch": ("주소가 다", "주소 불일치", "등기부 주소"),
    "q19_deposit_transfer_mismatch": ("이체 내역 금액", "보증금이랑 이체", "차액"),
    "q20_guarantee_check": ("전세보증금반환보증", "보증보험", "반환보증"),
}


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


def _contains_any(text: str, keywords: tuple[str, ...] | list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _related_scores(query: str) -> list[tuple[int, str]]:
    normalized = _normalize(query)
    scored: list[tuple[int, str]] = []

    for issue_id, keywords in RELATED_KEYWORDS.items():
        matched = [keyword for keyword in keywords if keyword in normalized]
        if not matched:
            continue
        score = sum(max(1, len(keyword) // 2) for keyword in matched)
        scored.append((score, issue_id))

    return sorted(scored, key=lambda item: (-item[0], item[1]))


def detect_primary_issue_id(query: str) -> str:
    """기존 RAG answer policy와 같은 우선순위로 대표 issue를 판정한다."""

    text = _normalize(query)
    if not text:
        raise ValueError("질문은 빈 문자열일 수 없습니다.")

    if _contains_any(text, ["공동명의", "공동소유자", "소유자가 두 명", "소유자 한 명만"]):
        return "q02_co_owner"

    if (
        _contains_any(
            text,
            [
                "등기부등본 소유자",
                "등기부 소유자",
                "등기부상 소유자",
                "소유자와 계약서",
                "소유자와 임대인",
                "임대인과 소유자",
            ],
        )
        and _contains_any(
            text,
            [
                "이름이 다",
                "이름이 달",
                "서로 다",
                "불일치",
                "다른 사람",
            ],
        )
    ):
        return "q03_owner_lessor_mismatch"

    if _contains_any(text, ["계좌가 바뀌", "계좌 변경", "변경된 계좌", "새 계좌"]):
        return "q05_account_change_before_contract"

    if _contains_any(text, ["부동산 계좌", "중개사 계좌", "제3자 계좌", "계좌로 계약금"]):
        return "q04_broker_account_payment"

    if (
        _contains_any(
            text,
            ["중개대상물 확인설명서", "확인설명서", "중개대상물"],
        )
        and _contains_any(
            text,
            [
                "계약서랑 다",
                "계약서와 다",
                "계약서 내용이 다",
                "내용이 다",
                "내용이 달",
                "불일치",
                "차이가",
                "틀리",
            ],
        )
    ):
        return "q06_broker_explanation_mismatch"

    if _contains_any(text, ["신탁등기", "신탁원부", "수탁자"]):
        return "q10_trust"
    if _contains_any(text, ["다가구", "선순위 보증금이 많", "선순위 임차인"]):
        return "q08_multiunit_priority"
    if _contains_any(text, ["근저당", "채권최고액", "저당권"]):
        return "q07_mortgage"
    if _contains_any(text, ["압류", "가압류", "가처분", "가등기", "권리 제한"]):
        return "q09_registry_restriction_warning"
    if _contains_any(text, ["집주인 아들", "대신 계약", "위임장 없이", "대리 권한", "대리인"]):
        return "q01_owner_proxy"
    if "전입신고" in text and "대항력" in text:
        return "q11_opposability_move_in"
    if "확정일자" in text and "우선변제권" in text:
        return "q12_fixed_date_priority"
    if _contains_any(text, ["집주인이 바뀌", "소유자가 바뀌", "소유자 변경", "새 소유자"]):
        return "q13_owner_change"
    if "특약" in text and _contains_any(text, ["계약금 반환", "반환 조건", "돌려받"]):
        return "q14_special_clause_deposit_return"
    if _contains_any(text, ["계약서 쓴 직후", "계약서 작성 직후", "계약서를 쓴 뒤", "바로 해야 할 절차"]):
        return "q15_after_contract_procedure"
    if _contains_any(text, ["주택 임대차신고", "임대차신고", "임대차 신고"]):
        return "q16_lease_report"
    if _contains_any(text, ["전입세대확인서", "전입세대 확인서", "전입세대열람"]):
        return "q17_household_certificate"
    if (
        "주소" in text
        and _contains_any(text, ["등기부등본", "등기부", "등기사항증명서"])
        and _contains_any(
            text,
            ["다른", "다르면", "달라", "다르", "차이", "불일치", "안 맞"],
        )
    ):
        return "q18_address_mismatch"
    if "계약서" in text and "보증금" in text and _contains_any(text, ["이체 내역", "이체내역", "송금 내역", "금액이 다", "차액"]):
        return "q19_deposit_transfer_mismatch"
    if _contains_any(text, ["전세보증금반환보증", "보증보험 가입 전", "반환보증 가입", "보증보험"]):
        return "q20_guarantee_check"

    # 계약서·등기부 파일 자체를 검토해 달라는 요청은 특정 위험이 확인되기 전
    # 단계다. 샘플 질문 번호를 강제로 주입하지 않고 문서 검토·계약 후 보호
    # 절차 상담으로 연결한 뒤, 실제 문서 분석 결과가 발견한 위험만 추가한다.
    document_markers = (
        "계약서", "등기부", "등기사항증명서", "pdf", "첨부", "업로드"
    )
    review_markers = (
        "확인", "검토", "분석", "요약", "읽어", "알려", "일치", "권리관계"
    )
    if _contains_any(text, document_markers) and _contains_any(text, review_markers):
        return "q15_after_contract_procedure"

    scored = _related_scores(text)
    if scored:
        return scored[0][1]

    raise UnsupportedConsultationIssueError(
        "현재 질문을 A파트 q01~q20 상담 유형으로 분류하지 못했습니다. "
        "issue_id를 직접 전달하거나 계약 상대방·계좌·등기부·계약 직후 절차처럼 "
        "상황을 조금 더 구체적으로 입력해 주세요."
    )


def route_issues(
    query: str,
    *,
    primary_issue_id: str | None = None,
    related_issue_ids: list[str] | tuple[str, ...] | None = None,
    max_related: int = 2,
) -> RoutedIssues:
    """명시한 issue를 우선하고, 없으면 질문 내용으로 자동 분류한다."""

    if max_related < 0:
        raise ValueError("max_related는 0 이상이어야 합니다.")

    primary = primary_issue_id or detect_primary_issue_id(query)
    get_issue_definition(primary)

    related: list[str] = []

    for issue_id in related_issue_ids or ():
        get_issue_definition(issue_id)
        if issue_id != primary and issue_id not in related:
            related.append(issue_id)

    if not related_issue_ids and max_related:
        scores = _related_scores(query)
        primary_score = next((score for score, item in scores if item == primary), 0)
        for score, issue_id in scores:
            if issue_id == primary:
                continue
            if score >= 4 or (primary_score and score >= max(3, primary_score - 2)):
                related.append(issue_id)
            if len(related) >= max_related:
                break

    return RoutedIssues(
        primary_issue_id=primary,
        related_issue_ids=tuple(related[:max_related]),
    )
