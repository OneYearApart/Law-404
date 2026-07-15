from __future__ import annotations

import json
import os
import re
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

def search_documents(**kwargs: Any):
    """RAG 의존성을 실제 검색 시점까지 지연 로드한다."""
    from backend.app.rag.retrievers.a_part import search_documents as _search
    return _search(**kwargs)


PROJECT_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(PROJECT_ROOT / "backend" / ".env")
load_dotenv(PROJECT_ROOT / ".env")


RISK_LEVELS = [
    "현재 입력 기준 중대한 보류 사유 미확인",
    "확인 필요",
    "주의 필요",
    "진행 보류 권장",
    "고위험 대응 전환 검토",
]


ROUTE_EVIDENCE_KEYWORDS: dict[str, list[str]] = {
    "owner_proxy": [
        "대리",
        "대리인",
        "대리권",
        "위임장",
        "위임",
        "소유자",
        "공동명의",
        "공동소유자",
        "계약 권한",
        "수령 권한",
    ],
    "account_payment": [
        "계좌",
        "예금주",
        "송금",
        "계약금",
        "잔금",
        "수령 권한",
        "지급",
        "이체",
        "보류",
    ],
    "account_change": [
        "계좌 변경",
        "새 계좌",
        "예금주",
        "계약상대방",
        "임대인",
        "확인",
        "송금",
        "보류",
    ],
    "deposit_transfer_mismatch": [
        "보증금",
        "이체 내역",
        "이체내역",
        "입금내역",
        "금액",
        "불일치",
        "계약서",
        "확인",
    ],
    "broker_explanation": [
        "중개대상물",
        "확인설명서",
        "확인·설명",
        "공인중개사",
        "권리관계",
        "불일치",
    ],
    "registry_risk": [
        "등기부등본",
        "권리관계",
        "근저당",
        "압류",
        "가압류",
        "가처분",
        "신탁",
        "선순위",
        "소유권",
    ],
    "lease_report": [
        "주택 임대차신고",
        "임대차신고",
        "임대차계약신고",
        "신고필증",
        "신고대상",
        "계약체결일",
    ],
    "protection_procedure": [
        "전입신고",
        "확정일자",
        "대항력",
        "우선변제권",
        "점유",
        "다음 날",
        "입주",
        "절차",
    ],
    "document_mismatch": [
        "계약서",
        "등기부등본",
        "주소",
        "금액",
        "불일치",
        "비교",
        "소유자",
        "임대인",
    ],
    "guarantee": [
        "전세보증금반환보증",
        "반환보증",
        "보증보험",
        "보증기관",
        "가입",
        "심사",
        "필요 서류",
    ],
    "owner_change": [
        "소유권 이전",
        "임대인 지위",
        "승계",
        "양수인",
        "보증금반환채무",
        "집주인 변경",
    ],
}


DIRECT_BODY_KEYWORDS: dict[str, list[str]] = {
    "owner_proxy": [
        "위임장",
        "대리권",
        "대리 권한",
        "위임 범위",
        "계약 권한",
        "수령 권한",
        "본인의 위임",
        "무권대리",
        "표현대리",
    ],
    "account_payment": [
        "계좌 예금주",
        "수령 권한",
        "계약금 송금",
        "잔금 송금",
        "제3자 계좌",
        "중개사 계좌",
    ],
    "account_change": [
        "계좌 변경",
        "새 계좌",
        "예금주 변경",
        "수령 권한",
    ],
    "deposit_transfer_mismatch": [
        "이체 내역",
        "이체내역",
        "입금내역",
        "금액 불일치",
        "보증금 금액",
    ],
    "broker_explanation": [
        "중개대상물 확인설명서",
        "중개대상물 확인·설명서",
        "확인설명서",
        "확인·설명 의무",
    ],
    "registry_risk": [
        "근저당",
        "압류",
        "가압류",
        "가처분",
        "신탁등기",
        "선순위 보증금",
    ],
    "lease_report": [
        "주택 임대차신고",
        "임대차계약신고",
        "신고필증",
    ],
    "protection_procedure": [
        "전입신고",
        "확정일자",
        "대항력",
        "우선변제권",
    ],
    "document_mismatch": [
        "주소 불일치",
        "금액 불일치",
        "계약서와 등기부등본",
        "문서 비교",
    ],
    "guarantee": [
        "전세보증금반환보증",
        "보증보험",
        "보증기관 심사",
    ],
    "owner_change": [
        "임대인 지위 승계",
        "소유권 이전",
        "보증금반환채무",
    ],
}


QUERY_STOPWORDS = {
    "어떻게",
    "괜찮나요",
    "되나요",
    "해야",
    "하나요",
    "있는데",
    "같은",
    "조금",
    "전에",
    "후에",
    "계약",
    "집주인",
    "임대인",
    "임차인",
}


class EvidenceStatus(str, Enum):
    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class RAGGenerationStatus(str, Enum):
    COMPLETED = "completed"
    PARTIAL_EVIDENCE = "partial_evidence"
    EVIDENCE_NOT_FOUND = "evidence_not_found"
    SEARCH_FAILED = "search_failed"
    GENERATION_FAILED = "generation_failed"
    VALIDATION_FAILED = "validation_failed"


class ConsultationContext(BaseModel):
    contract_stage: str = "잘 모르겠음"
    payment_status: str = "잘 모르겠음"
    contract_type: str = "잘 모르겠음"
    known_facts: list[str] = Field(default_factory=list, max_length=10)


class GeneratedAnswerBody(BaseModel):
    risk_level: Literal[
        "현재 입력 기준 중대한 보류 사유 미확인",
        "확인 필요",
        "주의 필요",
        "진행 보류 권장",
        "고위험 대응 전환 검토",
    ]
    core_judgment: str
    immediate_actions: list[str] = Field(default_factory=list, max_length=3)
    hold_actions: list[str] = Field(default_factory=list, max_length=3)
    reasons: list[str] = Field(default_factory=list, max_length=4)
    required_information: list[str] = Field(default_factory=list, max_length=6)
    follow_up_questions: list[str] = Field(default_factory=list, max_length=3)
    confirmation_message: str | None = None


class ReferenceItem(BaseModel):
    evidence_id: int
    collection: str
    document_id: str
    source_id: str | None = None
    source_type: str | None = None
    title: str | None = None
    issue_id: str | None = None
    similarity: float
    rerank_score: float | None = None
    text_preview: str


class DocumentSummarySection(BaseModel):
    title: str
    items: list[str] = Field(default_factory=list)


class DocumentSummary(BaseModel):
    source_count: int = Field(default=0, ge=0)
    sections: list[DocumentSummarySection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class APartAnswer(BaseModel):
    risk_level: str
    core_judgment: str
    immediate_actions: list[str]
    hold_actions: list[str]
    reasons: list[str]
    required_information: list[str]
    references: list[ReferenceItem]
    follow_up_questions: list[str]
    confirmation_message: str | None = None
    document_summary: DocumentSummary | None = None


class APartRAGResponse(BaseModel):
    query: str
    answer_code_version: str
    consultation_context: ConsultationContext
    evidence_status: EvidenceStatus
    generation_status: RAGGenerationStatus = RAGGenerationStatus.COMPLETED
    answer: APartAnswer
    selected_evidence: list[ReferenceItem]
    search_result_count: int
    search_code_version: str | None = None
    warnings: list[str] = Field(default_factory=list)


DEFAULT_CHAT_MODEL = "gpt-4o-mini"
ANSWER_CODE_VERSION = "answer-v19-generic-document-summary"


class RAGExecutionError(RuntimeError):
    generation_status = RAGGenerationStatus.VALIDATION_FAILED

    def __init__(
        self,
        message: str,
        *,
        search_result_count: int = 0,
        search_code_version: str | None = None,
    ) -> None:
        super().__init__(message)
        self.search_result_count = search_result_count
        self.search_code_version = search_code_version


class RAGSearchUnavailableError(RAGExecutionError):
    generation_status = RAGGenerationStatus.SEARCH_FAILED


class RAGEvidenceNotFoundError(RAGExecutionError):
    generation_status = RAGGenerationStatus.EVIDENCE_NOT_FOUND


class RAGEvidenceInsufficientError(RAGExecutionError):
    generation_status = RAGGenerationStatus.EVIDENCE_NOT_FOUND


class RAGAnswerGenerationError(RAGExecutionError):
    generation_status = RAGGenerationStatus.GENERATION_FAILED


class RAGAnswerValidationError(RAGExecutionError):
    generation_status = RAGGenerationStatus.VALIDATION_FAILED


def _require_openai_settings() -> tuple[str, str]:
    api_key = os.getenv("OPENAI_API_KEY")
    chat_model = os.getenv("OPENAI_CHAT_MODEL", DEFAULT_CHAT_MODEL).strip()

    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY가 없습니다. backend/.env를 확인하세요."
        )

    if not chat_model:
        chat_model = DEFAULT_CHAT_MODEL

    return api_key, chat_model


def _safe_metadata(result: dict[str, Any]) -> dict[str, Any]:
    metadata = result.get("metadata")

    if isinstance(metadata, dict):
        return metadata

    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
        except json.JSONDecodeError:
            return {}

        if isinstance(parsed, dict):
            return parsed

    return {}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _extract_query_tokens(query: str) -> list[str]:
    raw_tokens = re.findall(r"[가-힣A-Za-z0-9]+", query)
    tokens: list[str] = []

    for token in raw_tokens:
        normalized = token.strip().lower()

        if len(normalized) < 2:
            continue

        if normalized in QUERY_STOPWORDS:
            continue

        if normalized not in tokens:
            tokens.append(normalized)

    return tokens[:12]


def _collect_route_keywords(
    query: str,
    search_results: list[dict[str, Any]],
) -> list[str]:
    keywords: list[str] = []

    for result in search_results:
        route_ids = result.get("matched_route_ids") or []

        if not isinstance(route_ids, list):
            continue

        for route_id in route_ids:
            for keyword in ROUTE_EVIDENCE_KEYWORDS.get(str(route_id), []):
                if keyword not in keywords:
                    keywords.append(keyword)

    for token in _extract_query_tokens(query):
        if token not in keywords:
            keywords.append(token)

    return keywords


def _source_group_key(result: dict[str, Any]) -> str:
    metadata = _safe_metadata(result)

    parent_document_id = _normalize_text(
        metadata.get("parent_document_id")
    )
    source_id = _normalize_text(result.get("source_id"))
    document_id = _normalize_text(result.get("document_id"))

    return parent_document_id or source_id or document_id


def _evidence_text(result: dict[str, Any]) -> str:
    metadata = _safe_metadata(result)

    return " ".join(
        [
            _normalize_text(result.get("title")),
            _normalize_text(result.get("text")),
            _normalize_text(metadata.get("issue_id")),
            _normalize_text(metadata.get("issue_name")),
            _normalize_text(metadata.get("keywords")),
            _normalize_text(metadata.get("risk_signals")),
        ]
    ).lower()


def _count_keyword_hits(
    result: dict[str, Any],
    keywords: list[str],
) -> int:
    combined_text = _evidence_text(result)

    return sum(
        1
        for keyword in keywords
        if keyword.lower() in combined_text
    )


def _has_target_issue(result: dict[str, Any]) -> bool:
    metadata = _safe_metadata(result)
    issue_id = _normalize_text(metadata.get("issue_id"))
    target_issue_ids = result.get("target_issue_ids") or []

    if not issue_id or not isinstance(target_issue_ids, list):
        return False

    return issue_id in {str(item) for item in target_issue_ids}


def _is_summary_chunk(result: dict[str, Any]) -> bool:
    metadata = _safe_metadata(result)
    chunk_index = metadata.get("chunk_index")
    text = _normalize_text(result.get("text"))

    return chunk_index == 1 or text.startswith("[쟁점]")



def _matched_route_ids(
    search_results: list[dict[str, Any]],
) -> list[str]:
    route_ids: list[str] = []

    for result in search_results:
        values = result.get("matched_route_ids") or []
        if not isinstance(values, list):
            continue

        for value in values:
            route_id = str(value)
            if route_id and route_id not in route_ids:
                route_ids.append(route_id)

    return route_ids


def _direct_body_hits(
    result: dict[str, Any],
    route_ids: list[str],
) -> list[str]:
    body = _normalize_text(result.get("text")).lower()
    hits: list[str] = []

    for route_id in route_ids:
        for keyword in DIRECT_BODY_KEYWORDS.get(route_id, []):
            if keyword.lower() in body and keyword not in hits:
                hits.append(keyword)

    return hits


SPECIAL_CLAUSE_RETURN_APPROVED_DOCUMENT_IDS: set[str] = {
    "law404_special_clause_return_rule_c0001",
}

SPECIAL_CLAUSE_RETURN_SUPPORT_DOCUMENT_IDS: set[str] = {
    "law404_special_clause_return_rule_c0001",
    "moj_standard_contract_2023_10_06_p2_c0003",
    "hug_during_contract_cautions_phtml_c0001",
}

HOUSEHOLD_CERTIFICATE_APPROVED_DOCUMENT_IDS: set[str] = {
    "law404_household_certificate_timing_rule_c0001",
}


def _is_special_clause_return_query(query: str) -> bool:
    normalized_query = _normalize_text(query).lower()
    has_special_clause = any(
        keyword in normalized_query
        for keyword in [
            "특약",
            "반환 특약",
        ]
    )
    has_return_condition = any(
        keyword in normalized_query
        for keyword in [
            "계약금 반환",
            "반환 조건",
            "반환 사유",
            "계약금을 반환",
        ]
    )
    return has_special_clause and has_return_condition


def _is_approved_special_clause_return_evidence(
    result: dict[str, Any],
) -> bool:
    document_id = _normalize_text(result.get("document_id"))
    return document_id in SPECIAL_CLAUSE_RETURN_APPROVED_DOCUMENT_IDS


def _question_evidence_profile(
    query: str,
    route_ids: list[str],
) -> str:
    normalized_query = query.lower()

    # 같은 owner_proxy 라우트 안에서도 필요한 법률 근거가 다르므로
    # 질문별 근거 프로필을 먼저 분리한다.
    if any(
        keyword in normalized_query
        for keyword in [
            "공동명의",
            "공동소유",
            "소유자 한 명",
            "집주인이 여러 명",
        ]
    ):
        return "co_owner"

    if (
        any(
            keyword in normalized_query
            for keyword in [
                "소유자랑",
                "소유자와",
                "등기부등본 소유자",
                "등기부 소유자",
            ]
        )
        and any(
            keyword in normalized_query
            for keyword in [
                "임대인",
                "계약서",
                "이름이 다",
                "다른데",
                "불일치",
            ]
        )
    ):
        return "owner_lessor_mismatch"

    if any(
        keyword in normalized_query
        for keyword in [
            "집주인 아들",
            "대신 계약",
            "대리인",
            "위임장",
            "대리권",
        ]
    ):
        return "owner_proxy"

    has_broker_document = any(
        keyword in normalized_query
        for keyword in [
            "중개대상물 확인설명서",
            "중개대상물 확인·설명서",
            "중개대상물 확인ㆍ설명서",
            "확인설명서",
            "확인·설명서",
            "확인ㆍ설명서",
        ]
    )
    has_registry_document = any(
        keyword in normalized_query
        for keyword in [
            "등기부등본",
            "등기부",
            "등기사항증명서",
            "등기사항",
        ]
    )
    has_rights_topic = any(
        keyword in normalized_query
        for keyword in [
            "소유권 외 권리",
            "소유권외 권리",
            "권리사항",
            "권리 관계",
            "권리관계",
        ]
    )
    has_comparison_intent = any(
        keyword in normalized_query
        for keyword in [
            "비교",
            "확인",
            "다르",
            "불일치",
            "없다고",
            "없음",
        ]
    )
    if (
        has_broker_document
        and has_registry_document
        and has_rights_topic
        and has_comparison_intent
    ):
        return "broker_registry_comparison"

    if (
        "주소" in normalized_query
        and any(keyword in normalized_query for keyword in ["등기부등본", "등기부", "등기사항"])
        and any(keyword in normalized_query for keyword in ["다른", "다르면", "차이", "불일치"])
    ):
        return "address_mismatch"

    if (
        "계약서" in normalized_query
        and "보증금" in normalized_query
        and any(keyword in normalized_query for keyword in ["이체 내역", "이체내역", "송금 내역", "입금내역"])
        and any(keyword in normalized_query for keyword in ["다르", "차액", "불일치", "합계"])
    ):
        return "deposit_transfer_mismatch"

    if _is_special_clause_return_query(normalized_query):
        return "special_clause_return"

    if any(
        keyword in normalized_query
        for keyword in [
            "전입세대확인서",
            "전입세대 확인서",
            "전입세대 열람",
            "전입세대열람",
        ]
    ):
        return "household_certificate"

    if any(
        keyword in normalized_query
        for keyword in [
            "계약 직전",
            "계좌가 바뀌",
            "계좌 변경",
            "계좌를 바꾸",
            "변경된 계좌",
            "새 계좌",
        ]
    ):
        return "account_change"

    if any(
        keyword in normalized_query
        for keyword in [
            "부동산 계좌",
            "중개사 계좌",
            "제3자 계좌",
            "계약금을 보내",
            "계약금 송금",
            "계좌로 계약금",
            "예금주",
        ]
    ):
        return "account_payment"

    if any(
        keyword in normalized_query
        for keyword in [
            "다가구",
            "선순위 보증금",
            "선순위 임차인",
            "보증금이 많",
        ]
    ):
        return "multiunit_priority"

    if any(
        keyword in normalized_query
        for keyword in [
            "근저당",
            "근저당권",
            "채권최고액",
            "공동근저당",
        ]
    ):
        return "mortgage"

    if any(
        keyword in normalized_query
        for keyword in [
            "압류",
            "가압류",
            "가처분",
            "가등기",
            "권리 제한",
        ]
    ):
        return "registry_restriction"

    if any(
        keyword in normalized_query
        for keyword in [
            "신탁등기",
            "신탁원부",
            "수탁자",
            "신탁",
        ]
    ):
        return "trust_registry"

    if any(
        keyword in normalized_query
        for keyword in [
            "확정일자",
            "우선변제권",
            "우선변제",
        ]
    ):
        return "fixed_date_priority"

    if any(
        keyword in normalized_query
        for keyword in [
            "전입신고",
            "대항력",
            "주민등록",
            "주택 인도",
        ]
    ):
        return "opposability"

    if any(
        keyword in normalized_query
        for keyword in [
            "계약서 쓴 직후",
            "계약서 작성 직후",
            "계약서를 쓴 뒤",
            "계약서를 작성한 뒤",
            "바로 해야 할 절차",
        ]
    ):
        return "after_contract_procedure"

    if any(
        keyword in normalized_query
        for keyword in [
            "가입 전",
            "가입 전에",
            "보증 가입",
            "반환보증",
            "보증보험",
        ]
    ):
        return "guarantee_precheck"

    if "owner_proxy" in route_ids:
        return "owner_proxy"
    if "account_change" in route_ids:
        return "account_change"
    if "account_payment" in route_ids:
        return "account_payment"
    if "registry_risk" in route_ids:
        return "registry_restriction"
    if "protection_procedure" in route_ids:
        return "after_contract_procedure"
    if "guarantee" in route_ids:
        return "guarantee_precheck"

    return "default"


def _substantive_evidence_text(
    result: dict[str, Any],
) -> str:
    body = _normalize_text(result.get("text")).lower()
    source_type = _normalize_text(
        result.get("source_type")
    ).lower()

    if source_type == "law" and "[본문]" in body:
        return body.split("[본문]", 1)[1]

    if source_type == "precedent":
        if "[판시사항]" in body:
            return body.split("[판시사항]", 1)[1]
        if "[판결요지]" in body:
            return body.split("[판결요지]", 1)[1]

    return body

def _profile_body_hits(
    result: dict[str, Any],
    profile: str,
    route_ids: list[str],
) -> list[str]:
    body = _normalize_text(result.get("text")).lower()
    title = _normalize_text(result.get("title")).lower()
    source_type = _normalize_text(
        result.get("source_type")
    ).lower()
    substantive = _substantive_evidence_text(result)
    combined = f"{title} {body}"

    if profile == "owner_proxy":
        keywords = [
            "위임장",
            "대리권",
            "대리 권한",
            "위임 범위",
            "계약 권한",
            "수령 권한",
            "무권대리",
            "표현대리",
        ]
        return [
            keyword
            for keyword in keywords
            if keyword in substantive
        ]

    if profile == "co_owner":
        keywords = [
            "공동소유자 중 1인",
            "집주인이 여러 명",
            "지분이 1/2",
            "나머지 지분권자의 동의",
            "다른 공유자의 동의",
            "공유물의 처분",
            "공유물의 관리",
            "지분의 과반수",
            "공동으로 건물을 임대",
        ]
        return [
            keyword
            for keyword in keywords
            if keyword in substantive
        ]

    if profile == "owner_lessor_mismatch":
        keywords = [
            "계약당사자 확정",
            "타인의 이름으로 계약",
            "대리인을 통하여 계약",
            "본인과 사이에 계약",
            "임대인은 반드시 목적물 소유자일 것을 요하지",
            "임대인의 동의 없이",
            "임대 권한",
            "대리권",
        ]
        return [
            keyword
            for keyword in keywords
            if keyword in substantive
        ]

    if profile == "address_mismatch":
        contract_hits = [
            keyword for keyword in [
                "소재지",
                "도로명주소",
                "임차할부분",
                "동‧층‧호 정확히 기재",
                "동·층·호 정확히 기재",
            ]
            if keyword in substantive
        ]
        public_record_hits = [
            keyword for keyword in [
                "등기부등본상",
                "등기부",
                "건축물관리대장",
                "지번을 정확히 기재",
                "호수를 잘못 기재",
                "임대차계약서상",
            ]
            if keyword in substantive
        ]
        if not contract_hits and not public_record_hits:
            return []
        return [*contract_hits, *public_record_hits]

    if profile == "deposit_transfer_mismatch":
        contract_amount_hits = [
            keyword for keyword in [
                "보증금과 차임 및 관리비",
                "보 증 금",
                "계 약 금",
                "중 도 금",
                "잔 금",
                "지불하고 영수함",
                "영수자",
            ]
            if keyword in substantive
        ]
        payment_proof_hits = [
            keyword for keyword in [
                "전세보증금 지급서류",
                "영수증이나 이체내역",
                "이체내역",
                "무통장 입금증",
                "입금내역",
            ]
            if keyword in substantive
        ]
        if not contract_amount_hits and not payment_proof_hits:
            return []
        return [*contract_amount_hits, *payment_proof_hits]

    if profile == "special_clause_return":
        # 일반적인 특약 작성 안내만으로 계약금 반환 조건까지 충분하다고
        # 판단하지 않는다. 반환 사유·조건을 직접 설명하는 본문만 인정한다.
        keywords = [
            "계약금 반환",
            "반환 조건",
            "반환 사유",
            "계약금을 반환",
            "해제 시 반환",
            "계약금 등의 명목",
            "포기하지 않고",
            "임대차계약을 해제",
        ]
        return [
            keyword
            for keyword in keywords
            if keyword in substantive
        ]

    if profile == "household_certificate":
        certificate_hits = [
            keyword for keyword in [
                "전입세대확인서",
                "전입세대 열람",
                "전입세대열람",
                "세대주",
                "동거인",
                "전입일자",
            ]
            if keyword in substantive
        ]
        timing_hits = [
            keyword for keyword in [
                "계약 전",
                "계약체결 전",
                "잔금 전",
                "잔금 지급 전",
                "임대차기간이 시작하는 날까지",
            ]
            if keyword in substantive
        ]
        priority_hits = [
            keyword for keyword in [
                "선순위",
                "기존 전입",
                "점유",
                "선순위 임대차 정보",
            ]
            if keyword in substantive
        ]
        if not certificate_hits and not timing_hits and not priority_hits:
            return []
        return [*certificate_hits, *timing_hits, *priority_hits]

    if profile in {"account_payment", "account_change"}:
        # 실제 공식 원문 표현을 사용한다. 질문 문구를 그대로 포함한
        # 자체 제작 카드가 없어도 HUG·법무부·민법 근거를 조합할 수 있다.
        keywords = [
            "계약의 상대방이 주택 소유자 본인이 맞는지 확인",
            "정당한 대리권이 있는지 확인",
            "작성된 계약서가 사전에 협의된 내용과 일치하는지 확인",
            "계약 내용 확인",
            "계약시에 지불하고 영수함",
            "영수자",
            "영수증소지자에 대한 변제",
            "변제를 받을 권한이 없는 경우",
            "권한없음을 알았거나 알 수 있었을 경우",
            "변제받을 권한없는 자",
            "채권자가 이익을 받은 한도",
        ]
        return [
            keyword
            for keyword in keywords
            if keyword in substantive
        ]

    if profile == "mortgage":
        mortgage_keywords = [
            "근저당",
            "근저당권",
            "저당권",
            "채권최고액",
            "담보물권",
        ]
        deposit_keywords = [
            "보증금",
            "임차보증금",
            "전세보증금",
            "임대차",
        ]
        value_keywords = [
            "주택가액",
            "주택 가격",
            "시세",
            "감정가",
            "매각대금",
        ]

        mortgage_hits = [
            keyword for keyword in mortgage_keywords
            if keyword in substantive
        ]
        deposit_hits = [
            keyword for keyword in deposit_keywords
            if keyword in substantive
        ]
        value_hits = [
            keyword for keyword in value_keywords
            if keyword in substantive
        ]

        # 한 문서가 근저당+보증금 또는 보증금+주택가액처럼
        # 최소 두 역할을 직접 설명해야 선택 후보로 인정한다.
        group_count = sum(
            bool(values)
            for values in [mortgage_hits, deposit_hits, value_hits]
        )
        if not deposit_hits or group_count < 2:
            return []

        return [*mortgage_hits, *deposit_hits, *value_hits]

    if profile == "multiunit_priority":
        multiunit_keywords = ["다가구", "다세대"]
        senior_keywords = [
            "선순위 보증금",
            "선순위 임차인",
            "선순위 임차보증금",
            "임차보증금 총액",
            "보증금 합계",
        ]
        value_or_rights_keywords = [
            "주택가액",
            "시세",
            "감정가",
            "감정",
            "권리관계",
            "근저당",
            "채권최고액",
        ]

        multiunit_hits = [
            keyword for keyword in multiunit_keywords
            if keyword in substantive
        ]
        senior_hits = [
            keyword for keyword in senior_keywords
            if keyword in substantive
        ]
        value_or_rights_hits = [
            keyword for keyword in value_or_rights_keywords
            if keyword in substantive
        ]

        if not multiunit_hits or not senior_hits:
            return []

        return [*multiunit_hits, *senior_hits, *value_or_rights_hits]

    if profile == "broker_registry_comparison":
        broker_keywords = [
            "중개대상물 확인설명서",
            "중개대상물 확인·설명서",
            "중개대상물 확인ㆍ설명서",
            "확인설명서",
            "확인·설명서",
            "확인ㆍ설명서",
        ]
        rights_keywords = [
            "소유권 외의 권리사항",
            "소유권 외 권리사항",
            "소유권외의권리사항",
            "권리관계",
            "등기부",
            "등기사항증명서",
            "저당권",
            "근저당권",
        ]
        verification_keywords = [
            "확인·설명 의무",
            "확인ㆍ설명 의무",
            "성실",
            "정확하게 설명",
            "조사한 후",
            "자료요구에 불응",
            "기재하여야",
            "제시하고",
        ]

        broker_hits = [
            keyword
            for keyword in broker_keywords
            if keyword in combined
        ]
        rights_hits = [
            keyword
            for keyword in rights_keywords
            if keyword in substantive
            or keyword in combined
        ]
        verification_hits = [
            keyword
            for keyword in verification_keywords
            if keyword in substantive
            or keyword in combined
        ]

        if not broker_hits or not rights_hits:
            return []

        return [
            *broker_hits,
            *rights_hits,
            *verification_hits,
        ]

    if profile == "registry_restriction":
        risk_keywords = [
            "압류",
            "가압류",
            "가처분",
            "가등기",
            "경매개시",
        ]
        real_estate_keywords = [
            "등기",
            "부동산",
            "주택",
            "임대차",
            "임차보증금",
            "보증금",
            "대지",
            "건물",
            "저당권",
            "경매",
        ]

        risk_hits = [
            keyword
            for keyword in risk_keywords
            if keyword in substantive
        ]
        real_estate_hits = [
            keyword
            for keyword in real_estate_keywords
            if keyword in substantive
        ]

        if not risk_hits or not real_estate_hits:
            return []

        unrelated_execution_terms = [
            "유체동산",
            "채권양도",
            "제3채무자",
            "채권가압류",
        ]
        strong_real_estate_terms = [
            "주택임대차",
            "임차보증금",
            "부동산",
            "대지",
            "건물",
            "저당권",
            "등기",
        ]

        if (
            any(
                keyword in substantive
                for keyword in unrelated_execution_terms
            )
            and not any(
                keyword in substantive
                for keyword in strong_real_estate_terms
            )
        ):
            return []

        # 일반적인 가압류 신청·압류 절차 조문은
        # 주택 계약 전 등기 위험의 직접 근거로 사용하지 않는다.
        if source_type == "law" and not any(
            keyword in substantive
            for keyword in [
                "부동산",
                "주택",
                "임대차",
                "임차보증금",
                "등기",
                "경매",
            ]
        ):
            return []

        excluded_registry_topics = [
            "압류금지채권",
            "급여채권",
            "퇴직금",
            "퇴직연금",
            "부양료",
            "유족부조료",
            "채권양도",
            "제3채무자",
        ]

        if any(
            keyword in f"{title} {substantive}"
            for keyword in excluded_registry_topics
        ):
            return []

        return [*risk_hits, *real_estate_hits]

    if profile == "trust_registry":
        trust_keywords = [
            "신탁등기",
            "신탁원부",
            "부동산담보신탁",
            "신탁계약",
            "신탁",
        ]
        party_keywords = ["수탁자", "위탁자"]
        authority_keywords = [
            "임대권한",
            "임대 권한",
            "수탁자의 동의",
            "수탁자의 사전 승낙",
            "사전 승낙",
            "동의 없이 임대차계약",
            "신탁회사의 동의 없는 계약",
            "동의 없는 계약",
            "임대차계약 체결에 동의",
        ]

        trust_hits = [
            keyword for keyword in trust_keywords
            if keyword in substantive
        ]
        party_hits = [
            keyword for keyword in party_keywords
            if keyword in substantive
        ]
        authority_hits = [
            keyword for keyword in authority_keywords
            if keyword in substantive
        ]

        if not trust_hits or not authority_hits:
            return []

        return [*trust_hits, *party_hits, *authority_hits]

    if profile == "opposability":
        delivery_keywords = ["주택의 인도", "주택 인도", "인도"]
        registration_keywords = ["주민등록", "전입신고"]
        next_day_keywords = [
            "다음 날",
            "다음날",
            "익일",
            "다음 날 0시",
        ]
        effect_keywords = [
            "대항력",
            "제삼자에 대하여 효력",
            "제3자에 대하여 효력",
        ]

        delivery_hits = [
            keyword for keyword in delivery_keywords
            if keyword in substantive
        ]
        registration_hits = [
            keyword for keyword in registration_keywords
            if keyword in substantive
        ]
        next_day_hits = [
            keyword for keyword in next_day_keywords
            if keyword in substantive
        ]
        effect_hits = [
            keyword for keyword in effect_keywords
            if keyword in substantive
        ]

        if not all([
            delivery_hits,
            registration_hits,
            next_day_hits,
            effect_hits,
        ]):
            return []

        return [
            *delivery_hits,
            *registration_hits,
            *next_day_hits,
            *effect_hits,
        ]

    if profile == "fixed_date_priority":
        fixed_date_hits = [
            keyword for keyword in ["확정일자"]
            if keyword in substantive
        ]
        priority_hits = [
            keyword for keyword in ["우선변제권", "우선변제"]
            if keyword in substantive
        ]
        requirement_hits = [
            keyword
            for keyword in [
                "대항요건",
                "주택의 인도",
                "주택 인도",
                "주민등록",
                "전입신고",
            ]
            if keyword in substantive
        ]

        if not all([fixed_date_hits, priority_hits, requirement_hits]):
            return []

        return [*fixed_date_hits, *priority_hits, *requirement_hits]

    if profile == "after_contract_procedure":
        keywords = [
            "계약서 원본",
            "계약서 보관",
            "이체 내역",
            "이체내역",
            "영수증",
            "등기부등본",
            "권리관계",
            "잔금",
            "전입신고",
            "확정일자",
            "임대차신고",
            "주택 임대차신고",
            "대항력",
            "우선변제권",
        ]
        return [
            keyword
            for keyword in keywords
            if keyword in substantive
        ]

    if profile == "guarantee_precheck":
        guarantee_keywords = [
            "전세보증금반환보증",
            "반환보증",
            "보증보험",
        ]
        application_keywords = [
            "가입대상",
            "가입 조건",
            "가입조건",
            "신청절차",
            "보증신청",
            "서류제출 및 심사",
            "제출서류 안내",
            "제출서류",
            "심사 후",
            "심사사항",
            "보증서 발급",
        ]

        guarantee_hits = [
            keyword
            for keyword in guarantee_keywords
            if keyword in combined
        ]
        application_hits = [
            keyword
            for keyword in application_keywords
            if keyword in combined
        ]

        if not guarantee_hits or not application_hits:
            return []

        if "이행청구" in title:
            return []
        if "서식자료실" in title:
            return []
        if "안심전세포털" == title.strip():
            return []
        if "검색 총 0 건" in body:
            return []

        # 가입 전 근거는 상품안내 또는 실제 신청·심사·서류 설명이
        # 포함된 자료만 사용한다.
        if (
            "상품안내" not in title
            and "신청절차" not in body
            and "서류제출 및 심사" not in body
            and "제출서류 안내" not in body
        ):
            return []

        return [*guarantee_hits, *application_hits]

    return _direct_body_hits(result, route_ids)

def _profile_coverage_groups(
    result: dict[str, Any],
    profile: str,
) -> set[str]:
    body = _normalize_text(result.get("text")).lower()
    title = _normalize_text(result.get("title")).lower()
    combined = f"{title} {body}"
    groups: set[str] = set()

    if profile == "owner_proxy":
        if any(
            keyword in combined
            for keyword in [
                "임대인의 대리인과 계약",
                "위임장",
                "대리권",
                "무권대리",
            ]
        ):
            groups.add("authority_check")
        if any(
            keyword in combined
            for keyword in [
                "임차목적물 소재지",
                "계약의 목적",
                "인감증명서",
                "위임 범위",
                "권한을 증명",
            ]
        ):
            groups.add("scope_or_identity")
        if any(
            keyword in combined
            for keyword in [
                "본인에 대하여 효력이 없다",
                "추인",
                "손해를 배상할 책임",
            ]
        ):
            groups.add("legal_effect")

    elif profile == "co_owner":
        if any(
            keyword in combined
            for keyword in [
                "공동소유자 중 1인",
                "집주인이 여러 명",
                "공유물",
                "공유자",
            ]
        ):
            groups.add("co_owner")
        if any(
            keyword in combined
            for keyword in [
                "지분이 1/2",
                "지분의 과반수",
                "나머지 지분권자의 동의",
                "다른 공유자의 동의",
                "동의서를 받",
            ]
        ):
            groups.add("consent_or_share")

    elif profile == "owner_lessor_mismatch":
        if any(
            keyword in combined
            for keyword in [
                "계약당사자 확정",
                "타인의 이름으로 계약",
                "대리인을 통하여 계약",
                "본인과 사이에 계약",
            ]
        ):
            groups.add("party_or_authority")
        if any(
            keyword in combined
            for keyword in [
                "임대인은 반드시 목적물 소유자일 것을 요하지",
                "임대인의 동의 없이",
                "소유자",
                "임대인",
            ]
        ):
            groups.add("owner_mismatch")

    elif profile == "address_mismatch":
        if any(keyword in combined for keyword in [
            "소재지", "도로명주소", "임차할부분", "동‧층‧호 정확히 기재", "동·층·호 정확히 기재"
        ]):
            groups.add("contract_property_identifier")
        if any(keyword in combined for keyword in [
            "등기부등본상", "등기부", "건축물관리대장", "지번을 정확히 기재", "호수를 잘못 기재", "임대차계약서상"
        ]):
            groups.add("official_record_identifier")

    elif profile == "deposit_transfer_mismatch":
        if any(keyword in combined for keyword in [
            "보증금과 차임 및 관리비", "보 증 금", "계 약 금", "중 도 금", "잔 금", "지불하고 영수함", "영수자"
        ]):
            groups.add("contract_amount_schedule")
        if any(keyword in combined for keyword in [
            "전세보증금 지급서류", "영수증이나 이체내역", "이체내역", "무통장 입금증", "입금내역"
        ]):
            groups.add("payment_proof")

    elif profile == "special_clause_return":
        if any(
            keyword in combined
            for keyword in [
                "계약금 반환",
                "반환 조건",
                "반환 사유",
                "계약금을 반환",
                "해제 시 반환",
            ]
        ) or (
            "계약금 등의 명목" in combined
            and "포기하지 않고" in combined
            and "임대차계약을 해제" in combined
        ):
            groups.add("return_condition")
        if "특약" in combined:
            groups.add("special_clause")

    elif profile == "household_certificate":
        if any(
            keyword in combined
            for keyword in [
                "전입세대확인서",
                "전입세대 열람",
                "전입세대열람",
                "세대주",
                "동거인",
                "전입일자",
            ]
        ):
            groups.add("certificate_scope")
        if any(keyword in combined for keyword in ["계약 전", "계약체결 전"]):
            groups.add("contract_timing")
        if any(
            keyword in combined
            for keyword in [
                "잔금 전",
                "잔금 지급 전",
                "임대차기간이 시작하는 날까지",
            ]
        ):
            groups.add("balance_timing")
        if any(
            keyword in combined
            for keyword in [
                "선순위",
                "기존 전입",
                "점유",
                "선순위 임대차 정보",
            ]
        ):
            groups.add("priority_context")

    elif profile in {"account_payment", "account_change"}:
        if any(
            keyword in combined
            for keyword in [
                "계약의 상대방이 주택 소유자 본인이 맞는지 확인",
                "정당한 대리권이 있는지 확인",
                "영수증소지자에 대한 변제",
                "변제를 받을 권한이 없는 경우",
                "변제받을 권한없는 자",
            ]
        ):
            groups.add("recipient_authority")

        if any(
            keyword in combined
            for keyword in [
                "계약금",
                "계약시에 지불하고 영수함",
                "영수자",
                "보증금과 차임",
            ]
        ):
            groups.add("payment_record")

        if any(
            keyword in combined
            for keyword in [
                "작성된 계약서가 사전에 협의된 내용과 일치하는지 확인",
                "계약 내용 확인",
                "계약내용 확인",
            ]
        ):
            groups.add("agreed_terms")

        if any(
            keyword in combined
            for keyword in [
                "권한없음을 알았거나 알 수 있었을 경우",
                "채권자가 이익을 받은 한도",
            ]
        ):
            groups.add("legal_effect")

    elif profile == "mortgage":
        if any(
            keyword in combined
            for keyword in [
                "근저당", "근저당권", "저당권", "채권최고액", "담보물권"
            ]
        ):
            groups.add("mortgage")
        if any(
            keyword in combined
            for keyword in ["보증금", "임차보증금", "전세보증금", "임대차"]
        ):
            groups.add("deposit")
        if any(
            keyword in combined
            for keyword in ["주택가액", "주택 가격", "시세", "감정가", "매각대금"]
        ):
            groups.add("property_value")

    elif profile == "multiunit_priority":
        if any(keyword in combined for keyword in ["다가구", "다세대"]):
            groups.add("multiunit")
        if any(
            keyword in combined
            for keyword in [
                "선순위 보증금",
                "선순위 임차인",
                "선순위 임차보증금",
                "임차보증금 총액",
                "보증금 합계",
            ]
        ):
            groups.add("senior_deposit")
        if any(
            keyword in combined
            for keyword in [
                "주택가액", "시세", "감정가", "감정", "권리관계", "근저당", "채권최고액"
            ]
        ):
            groups.add("value_or_rights")

    elif profile == "broker_registry_comparison":
        if any(
            keyword in combined
            for keyword in [
                "중개대상물 확인설명서",
                "중개대상물 확인·설명서",
                "중개대상물 확인ㆍ설명서",
                "확인설명서",
                "확인·설명서",
                "확인ㆍ설명서",
            ]
        ):
            groups.add("broker_document")
        if any(
            keyword in combined
            for keyword in [
                "소유권 외의 권리사항",
                "소유권 외 권리사항",
                "소유권외의권리사항",
                "등기부",
                "등기사항증명서",
                "권리관계",
                "저당권",
                "근저당권",
            ]
        ):
            groups.add("registry_rights")
        if any(
            keyword in combined
            for keyword in [
                "확인·설명 의무",
                "확인ㆍ설명 의무",
                "성실",
                "정확하게 설명",
                "조사한 후",
                "자료요구에 불응",
                "기재하여야",
                "제시하고",
            ]
        ):
            groups.add("verification_duty")

    elif profile == "registry_restriction":
        if any(
            keyword in combined
            for keyword in ["등기부", "등기", "권리관계"]
        ):
            groups.add("registry")
        if any(
            keyword in combined
            for keyword in ["압류", "가압류", "가처분", "가등기"]
        ):
            groups.add("restriction")
        if any(
            keyword in combined
            for keyword in ["말소", "해소", "경매", "선순위", "보증금"]
        ):
            groups.add("effect_or_action")

    elif profile == "trust_registry":
        if any(
            keyword in combined
            for keyword in [
                "신탁등기",
                "신탁원부",
                "부동산담보신탁",
                "신탁계약",
                "신탁",
            ]
        ):
            groups.add("trust_structure")
        if any(keyword in combined for keyword in ["수탁자", "위탁자"]):
            groups.add("trust_parties")
        if any(
            keyword in combined
            for keyword in [
                "임대권한",
                "임대 권한",
                "수탁자의 동의",
                "수탁자의 사전 승낙",
                "사전 승낙",
                "동의 없이 임대차계약",
                "신탁회사의 동의 없는 계약",
                "동의 없는 계약",
                "임대차계약 체결에 동의",
            ]
        ):
            groups.add("authority_or_consent")

    elif profile == "opposability":
        if any(
            keyword in combined
            for keyword in ["주택의 인도", "주택 인도", "인도"]
        ):
            groups.add("delivery")
        if any(keyword in combined for keyword in ["주민등록", "전입신고"]):
            groups.add("registration")
        if any(
            keyword in combined
            for keyword in ["다음 날", "다음날", "익일", "다음 날 0시"]
        ):
            groups.add("next_day")
        if any(
            keyword in combined
            for keyword in [
                "대항력",
                "제삼자에 대하여 효력",
                "제3자에 대하여 효력",
            ]
        ):
            groups.add("opposability_effect")

    elif profile == "fixed_date_priority":
        if "확정일자" in combined:
            groups.add("fixed_date")
        if any(keyword in combined for keyword in ["우선변제권", "우선변제"]):
            groups.add("priority_right")
        if any(
            keyword in combined
            for keyword in [
                "대항요건",
                "주택의 인도",
                "주택 인도",
                "주민등록",
                "전입신고",
            ]
        ):
            groups.add("opposability_requirements")

    elif profile == "after_contract_procedure":
        if any(
            keyword in combined
            for keyword in [
                "계약서 원본",
                "계약서 보관",
                "이체 내역",
                "이체내역",
                "영수증",
            ]
        ):
            groups.add("records")
        if any(
            keyword in combined
            for keyword in ["등기부등본", "권리관계", "잔금"]
        ):
            groups.add("pre_balance")
        if any(
            keyword in combined
            for keyword in ["임대차신고", "주택 임대차신고"]
        ):
            groups.add("lease_report")
        if any(
            keyword in combined
            for keyword in [
                "전입신고",
                "확정일자",
                "대항력",
                "우선변제권",
            ]
        ):
            groups.add("protection")

    elif profile == "guarantee_precheck":
        if any(
            keyword in combined
            for keyword in ["가입대상", "가입 조건", "가입조건"]
        ):
            groups.add("eligibility")
        if any(
            keyword in combined
            for keyword in [
                "신청절차",
                "보증신청",
                "서류제출",
                "제출서류",
            ]
        ):
            groups.add("application")
        if any(
            keyword in combined
            for keyword in ["심사", "심사 후", "심사사항"]
        ):
            groups.add("review")
        if any(
            keyword in combined
            for keyword in ["보증료", "보증서 발급"]
        ):
            groups.add("issuance")

    return groups


def _is_direct_answer_evidence(
    result: dict[str, Any],
    route_ids: list[str],
    profile: str = "default",
) -> bool:
    return bool(
        _profile_body_hits(
            result=result,
            profile=profile,
            route_ids=route_ids,
        )
    )


def _answer_evidence_score(
    result: dict[str, Any],
    keywords: list[str],
    profile: str,
) -> float:
    rerank_score = float(result.get("rerank_score") or 0.0)
    similarity = float(result.get("similarity") or 0.0)
    base_score = rerank_score if rerank_score > 0 else similarity

    keyword_bonus = min(
        _count_keyword_hits(result, keywords) * 0.025,
        0.15,
    )
    issue_bonus = 0.18 if _has_target_issue(result) else 0.0
    summary_bonus = 0.03 if _is_summary_chunk(result) else 0.0

    title = _normalize_text(result.get("title")).lower()
    body = _normalize_text(result.get("text")).lower()
    source_type = _normalize_text(
        result.get("source_type")
    ).lower()
    profile_bonus = 0.0
    profile_penalty = 0.0

    if profile in {
        "owner_proxy",
        "co_owner",
        "owner_lessor_mismatch",
    }:
        profile_bonus += min(
            len(_profile_coverage_groups(result, profile)) * 0.18,
            0.36,
        )
        if "주택임대차보호법 해설집" in title:
            profile_bonus += 0.28

    elif profile == "address_mismatch":
        profile_bonus += min(
            len(_profile_coverage_groups(result, profile)) * 0.24,
            0.48,
        )
        document_id = _normalize_text(result.get("document_id"))
        if document_id in {
            "moj_standard_contract_2023_10_06_p1_c0001",
            "prec_196703_01_owner_proxy__part_003",
        }:
            profile_bonus += 0.36

    elif profile == "deposit_transfer_mismatch":
        profile_bonus += min(
            len(_profile_coverage_groups(result, profile)) * 0.24,
            0.48,
        )
        document_id = _normalize_text(result.get("document_id"))
        if document_id in {
            "moj_standard_contract_2023_10_06_p1_c0002",
            "hug_guarantee_goods_phtml_c0001",
        }:
            profile_bonus += 0.36
        if "이행청구" in title:
            profile_penalty += 0.35

    elif profile == "special_clause_return":
        profile_bonus += min(
            len(_profile_coverage_groups(result, profile)) * 0.16,
            0.32,
        )
        document_id = _normalize_text(result.get("document_id"))
        if document_id == "law404_special_clause_return_rule_c0001":
            profile_bonus += 0.80
        if document_id == "moj_standard_contract_2023_10_06_p2_c0003":
            profile_bonus += 0.42
        if document_id == "hug_during_contract_cautions_phtml_c0001":
            profile_bonus += 0.24

    elif profile == "household_certificate":
        profile_bonus += min(
            len(_profile_coverage_groups(result, profile)) * 0.16,
            0.64,
        )
        document_id = _normalize_text(result.get("document_id"))
        if document_id == "law404_household_certificate_timing_rule_c0001":
            profile_bonus += 0.80
        if document_id == "gov_household_certificate_phtml_c0005":
            profile_bonus += 0.42
        if document_id == "moj_standard_contract_2023_10_06_p2_c0003":
            profile_bonus += 0.30

    elif profile in {"account_payment", "account_change"}:
        profile_bonus += min(
            len(_profile_coverage_groups(result, profile)) * 0.16,
            0.48,
        )
        if "계약 체결 시 유의사항" in title:
            profile_bonus += 0.24
        if "주택임대차 표준계약서" in title:
            profile_bonus += 0.20
        if "민법" == title.strip():
            profile_bonus += 0.18
        if "이행청구" in title or "상품안내" in title:
            profile_penalty += 0.35

    elif profile in {"mortgage", "multiunit_priority"}:
        profile_bonus += min(
            len(_profile_coverage_groups(result, profile)) * 0.18,
            0.54,
        )
        metadata = _safe_metadata(result)
        issue_id = _normalize_text(metadata.get("issue_id"))
        if profile == "mortgage" and issue_id == "03_mortgage":
            profile_bonus += 0.20
        if profile == "multiunit_priority" and issue_id == "04_multiunit_priority":
            profile_bonus += 0.22

    elif profile == "broker_registry_comparison":
        coverage = _profile_coverage_groups(
            result,
            profile,
        )
        profile_bonus += min(
            len(coverage) * 0.20,
            0.60,
        )
        if any(
            keyword in title
            for keyword in [
                "공인중개사법 시행규칙",
                "주택임대차 표준계약서",
            ]
        ):
            profile_bonus += 0.24
        if source_type == "precedent":
            profile_bonus += 0.16

    elif profile == "registry_restriction":
        if "등기부 위험 신호" in body:
            profile_bonus += 0.25
        if any(
            keyword in body
            for keyword in ["유체동산", "채권가압류", "채권양도"]
        ):
            profile_penalty += 0.20

    elif profile == "trust_registry":
        profile_bonus += min(
            len(_profile_coverage_groups(result, profile)) * 0.18,
            0.54,
        )
        metadata = _safe_metadata(result)
        issue_id = _normalize_text(metadata.get("issue_id"))
        document_id = _normalize_text(result.get("document_id"))
        if issue_id == "06_trust":
            profile_bonus += 0.24
        if document_id in {
            "prec_206299_06_trust__part_001",
            "prec_231467_06_trust__part_001",
            "hug_fraud_cases_actions_phtml_c0001",
        }:
            profile_bonus += 0.24

    elif profile == "opposability":
        profile_bonus += min(
            len(_profile_coverage_groups(result, profile)) * 0.16,
            0.64,
        )
        metadata = _safe_metadata(result)
        issue_id = _normalize_text(metadata.get("issue_id"))
        document_id = _normalize_text(result.get("document_id"))
        if issue_id == "07_opposability_fixed_date":
            profile_bonus += 0.22
        if document_id in {
            "law_001248_제3조",
            "hug_after_contract_cautions_phtml_c0002",
            "prec_196635_07_opposability__part_001",
        }:
            profile_bonus += 0.26

    elif profile == "fixed_date_priority":
        profile_bonus += min(
            len(_profile_coverage_groups(result, profile)) * 0.18,
            0.54,
        )
        metadata = _safe_metadata(result)
        issue_id = _normalize_text(metadata.get("issue_id"))
        document_id = _normalize_text(result.get("document_id"))
        if issue_id == "08_priority_payment":
            profile_bonus += 0.24
        if document_id in {
            "law_001248_제3조의2__part_001",
            "prec_195162_08_priority_payment__part_001",
            "prec_191649_08_priority_payment__part_001",
        }:
            profile_bonus += 0.24

    elif profile == "after_contract_procedure":
        profile_bonus += min(
            len(_profile_coverage_groups(result, profile)) * 0.10,
            0.30,
        )

    elif profile == "guarantee_precheck":
        if "상품안내" in title:
            profile_bonus += 0.30
        if "이행청구" in title:
            profile_penalty += 0.40
        if "서식자료실" in title:
            profile_penalty += 0.25

    return (
        base_score
        + keyword_bonus
        + issue_bonus
        + summary_bonus
        + profile_bonus
        - profile_penalty
    )


def select_answer_evidence(
    query: str,
    search_results: list[dict[str, Any]],
    max_items: int = 5,
) -> list[dict[str, Any]]:
    if max_items <= 0:
        raise ValueError("max_items는 1 이상이어야 합니다.")

    if not search_results:
        return []

    keywords = _collect_route_keywords(query, search_results)
    route_ids = _matched_route_ids(search_results)
    profile = _question_evidence_profile(query, route_ids)
    candidates: list[dict[str, Any]] = []

    # 계약금 반환 특약은 일반적인 결제 문서를 섞지 않는다.
    # 승인된 서비스 카드와 그 카드가 참조하는 공식 원문만 선택 후보로 둔다.
    if profile == "special_clause_return":
        search_results = [
            result
            for result in search_results
            if _normalize_text(result.get("document_id"))
            in SPECIAL_CLAUSE_RETURN_SUPPORT_DOCUMENT_IDS
        ]

    for result in search_results:
        copied = dict(result)
        direct_hits = _profile_body_hits(
            result=copied,
            profile=profile,
            route_ids=route_ids,
        )
        coverage_groups = sorted(
            _profile_coverage_groups(copied, profile)
        )

        copied["answer_evidence_profile"] = profile
        copied["answer_direct_body_hits"] = direct_hits
        copied["answer_direct_body_match"] = bool(direct_hits)
        copied["answer_coverage_groups"] = coverage_groups
        copied["answer_evidence_score"] = round(
            _answer_evidence_score(
                result=copied,
                keywords=keywords,
                profile=profile,
            )
            + min(len(direct_hits) * 0.08, 0.32),
            6,
        )
        copied["answer_keyword_hits"] = _count_keyword_hits(
            copied,
            keywords,
        )
        copied["answer_target_issue_match"] = _has_target_issue(
            copied
        )

        if direct_hits:
            candidates.append(copied)

    candidates.sort(
        key=lambda item: (
            len(item.get("answer_coverage_groups") or []),
            len(item.get("answer_direct_body_hits") or []),
            float(item.get("answer_evidence_score") or 0.0),
            float(item.get("rerank_score") or 0.0),
            float(item.get("similarity") or 0.0),
        ),
        reverse=True,
    )

    profile_item_limits = {
        "owner_proxy": 3,
        "co_owner": 3,
        "owner_lessor_mismatch": 2,
        "address_mismatch": 2,
        "deposit_transfer_mismatch": 2,
        "special_clause_return": 3,
        "household_certificate": 3,
        "account_payment": 3,
        "account_change": 3,
        "mortgage": 3,
        "multiunit_priority": 3,
        "broker_registry_comparison": 3,
        "registry_restriction": 3,
        "trust_registry": 3,
        "opposability": 3,
        "fixed_date_priority": 3,
        "after_contract_procedure": 3,
        "guarantee_precheck": 2,
    }
    item_limit = min(
        max_items,
        profile_item_limits.get(profile, max_items),
    )

    selected: list[dict[str, Any]] = []
    selected_source_keys: set[str] = set()
    covered_groups: set[str] = set()

    # 절차·보증 질문은 먼저 서로 다른 설명 역할을 가진 근거를 고른다.
    if profile in {
        "owner_proxy",
        "co_owner",
        "owner_lessor_mismatch",
        "address_mismatch",
        "deposit_transfer_mismatch",
        "special_clause_return",
        "household_certificate",
        "account_payment",
        "account_change",
        "mortgage",
        "multiunit_priority",
        "broker_registry_comparison",
        "after_contract_procedure",
        "guarantee_precheck",
        "registry_restriction",
        "trust_registry",
        "opposability",
        "fixed_date_priority",
    }:
        remaining = list(candidates)

        while remaining and len(selected) < item_limit:
            remaining.sort(
                key=lambda item: (
                    len(
                        set(item.get("answer_coverage_groups") or [])
                        - covered_groups
                    ),
                    float(item.get("answer_evidence_score") or 0.0),
                ),
                reverse=True,
            )

            picked = None

            for candidate in remaining:
                source_key = _source_group_key(candidate)
                if source_key not in selected_source_keys:
                    picked = candidate
                    break

            if picked is None:
                break

            selected.append(picked)
            selected_source_keys.add(_source_group_key(picked))
            covered_groups.update(
                picked.get("answer_coverage_groups") or []
            )
            remaining.remove(picked)

    else:
        for result in candidates:
            source_key = _source_group_key(result)

            if source_key in selected_source_keys:
                continue

            selected.append(result)
            selected_source_keys.add(source_key)

            if len(selected) >= item_limit:
                break

    return selected


def determine_evidence_status(
    query: str,
    selected_evidence: list[dict[str, Any]],
    search_results: list[dict[str, Any]],
) -> EvidenceStatus:
    route_ids = _matched_route_ids(search_results)
    profile = _question_evidence_profile(query, route_ids)

    direct_items = [
        item
        for item in selected_evidence
        if _is_direct_answer_evidence(
            result=item,
            route_ids=route_ids,
            profile=profile,
        )
    ]

    if profile == "owner_proxy":
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        if (
            direct_items
            and "authority_check" in coverage
            and (
                "scope_or_identity" in coverage
                or "legal_effect" in coverage
            )
        ):
            return EvidenceStatus.SUFFICIENT
        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "co_owner":
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        if {"co_owner", "consent_or_share"}.issubset(coverage):
            return EvidenceStatus.SUFFICIENT
        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "owner_lessor_mismatch":
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        if {"party_or_authority", "owner_mismatch"}.issubset(coverage):
            return EvidenceStatus.SUFFICIENT
        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "address_mismatch":
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        if (
            len(direct_items) >= 2
            and {
                "contract_property_identifier",
                "official_record_identifier",
            }.issubset(coverage)
        ):
            return EvidenceStatus.SUFFICIENT
        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "deposit_transfer_mismatch":
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        if (
            len(direct_items) >= 2
            and {
                "contract_amount_schedule",
                "payment_proof",
            }.issubset(coverage)
        ):
            return EvidenceStatus.SUFFICIENT
        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "special_clause_return":
        approved_direct_items = [
            item
            for item in direct_items
            if _is_approved_special_clause_return_evidence(item)
        ]
        official_support_items = [
            item
            for item in direct_items
            if _normalize_text(item.get("source_type")).lower()
            != "derived_rule"
        ]

        # 승인된 서비스 카드가 반환 조건을 직접 정리하고,
        # 별도의 공식 원문이 특약 또는 반환 법적 효과를 뒷받침할 때만
        # sufficient로 판단한다.
        approved_complete = any(
            {"special_clause", "return_condition"}.issubset(
                _profile_coverage_groups(item, profile)
            )
            for item in approved_direct_items
        )
        if approved_complete and official_support_items:
            return EvidenceStatus.SUFFICIENT

        if search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "household_certificate":
        approved_items = [
            item
            for item in direct_items
            if _normalize_text(item.get("document_id"))
            in HOUSEHOLD_CERTIFICATE_APPROVED_DOCUMENT_IDS
        ]
        official_support_items = [
            item
            for item in direct_items
            if _normalize_text(item.get("source_type")).lower()
            != "derived_rule"
        ]
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        approved_complete = any(
            {
                "certificate_scope",
                "contract_timing",
                "balance_timing",
                "priority_context",
            }.issubset(_profile_coverage_groups(item, profile))
            for item in approved_items
        )
        if approved_complete and official_support_items and {
            "certificate_scope",
            "contract_timing",
            "balance_timing",
            "priority_context",
        }.issubset(coverage):
            return EvidenceStatus.SUFFICIENT

        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile in {"account_payment", "account_change"}:
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        if profile == "account_payment":
            required = {"recipient_authority", "payment_record"}
        else:
            required = {
                "recipient_authority",
                "agreed_terms",
                "payment_record",
            }

        if len(direct_items) >= 2 and required.issubset(coverage):
            return EvidenceStatus.SUFFICIENT
        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "mortgage":
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        if (
            len(direct_items) >= 2
            and {"mortgage", "deposit", "property_value"}.issubset(coverage)
        ):
            return EvidenceStatus.SUFFICIENT
        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "multiunit_priority":
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        if (
            len(direct_items) >= 2
            and {"multiunit", "senior_deposit", "value_or_rights"}.issubset(coverage)
        ):
            return EvidenceStatus.SUFFICIENT
        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "broker_registry_comparison":
        coverage = set().union(
            *[
                _profile_coverage_groups(
                    item,
                    profile,
                )
                for item in direct_items
            ]
        ) if direct_items else set()

        if (
            len(direct_items) >= 2
            and {
                "broker_document",
                "registry_rights",
                "verification_duty",
            }.issubset(coverage)
        ):
            return EvidenceStatus.SUFFICIENT
        if direct_items:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "registry_restriction":
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        if (
            len(direct_items) >= 2
            and {"registry", "restriction"}.issubset(coverage)
        ):
            return EvidenceStatus.SUFFICIENT
        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "trust_registry":
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        if (
            len(direct_items) >= 2
            and {
                "trust_structure",
                "trust_parties",
                "authority_or_consent",
            }.issubset(coverage)
        ):
            return EvidenceStatus.SUFFICIENT
        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "opposability":
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        if (
            len(direct_items) >= 2
            and {
                "delivery",
                "registration",
                "next_day",
                "opposability_effect",
            }.issubset(coverage)
        ):
            return EvidenceStatus.SUFFICIENT
        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "fixed_date_priority":
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        if (
            len(direct_items) >= 2
            and {
                "fixed_date",
                "priority_right",
                "opposability_requirements",
            }.issubset(coverage)
        ):
            return EvidenceStatus.SUFFICIENT
        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "after_contract_procedure":
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        # 계약 직후 답변 전체를 뒷받침하려면 기록 보관·잔금 전 확인·
        # 신고/보호 절차 중 최소 세 역할의 근거가 필요하다.
        if len(coverage) >= 3:
            return EvidenceStatus.SUFFICIENT
        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if profile == "guarantee_precheck":
        coverage = set().union(
            *[
                _profile_coverage_groups(item, profile)
                for item in direct_items
            ]
        ) if direct_items else set()

        if (
            direct_items
            and "application" in coverage
            and (
                "review" in coverage
                or "eligibility" in coverage
                or "issuance" in coverage
            )
        ):
            return EvidenceStatus.SUFFICIENT
        if direct_items or search_results:
            return EvidenceStatus.PARTIAL
        return EvidenceStatus.INSUFFICIENT

    if len(direct_items) >= 2:
        return EvidenceStatus.SUFFICIENT

    if len(direct_items) == 1:
        return EvidenceStatus.PARTIAL

    has_weak_candidate = any(
        _has_target_issue(item)
        or float(item.get("similarity") or 0.0) >= 0.35
        for item in search_results
    )

    if has_weak_candidate:
        return EvidenceStatus.PARTIAL

    return EvidenceStatus.INSUFFICIENT


def _build_reference_preview(result: dict[str, Any]) -> str:
    text = _normalize_text(result.get("text"))
    document_id = _normalize_text(result.get("document_id"))

    # 긴 공식 문서에서 실제 선택 근거가 앞 500자 밖에 있는 경우에는
    # 문서 첫 부분이 아니라 근거 문구 주변을 참고자료 미리보기로 제공한다.
    # q19의 HUG 상품안내는 지급 증빙 문구가 약 700자 이후에 있어
    # 기존 첫 500자 미리보기만으로는 선택 이유를 확인할 수 없었다.
    focus_keywords_by_document: dict[str, tuple[str, ...]] = {
        "hug_guarantee_goods_phtml_c0001": (
            "전세보증금 지급서류",
            "영수증이나 이체내역",
            "이체내역",
            "무통장 입금증",
        ),
    }

    focus_keywords = focus_keywords_by_document.get(document_id, ())
    focus_positions = [
        text.find(keyword)
        for keyword in focus_keywords
        if text.find(keyword) >= 0
    ]

    if focus_positions:
        focus_index = min(focus_positions)
        start = max(0, focus_index - 180)
        end = min(len(text), focus_index + 500)
        preview = text[start:end]

        if start > 0:
            preview = "..." + preview
        if end < len(text):
            preview += "..."

        return preview

    return text[:500] + "..." if len(text) > 500 else text


def _build_reference_items(
    selected_evidence: list[dict[str, Any]],
) -> list[ReferenceItem]:
    references: list[ReferenceItem] = []

    for index, result in enumerate(selected_evidence, start=1):
        metadata = _safe_metadata(result)

        references.append(
            ReferenceItem(
                evidence_id=index,
                collection=_normalize_text(result.get("collection")),
                document_id=_normalize_text(result.get("document_id")),
                source_id=(
                    _normalize_text(result.get("source_id")) or None
                ),
                source_type=(
                    _normalize_text(result.get("source_type")) or None
                ),
                title=_normalize_text(result.get("title")) or None,
                issue_id=(
                    _normalize_text(metadata.get("issue_id")) or None
                ),
                similarity=round(
                    float(result.get("similarity") or 0.0),
                    6,
                ),
                rerank_score=(
                    round(
                        float(result.get("rerank_score") or 0.0),
                        6,
                    )
                    if result.get("rerank_score") is not None
                    else None
                ),
                text_preview=_build_reference_preview(result),
            )
        )

    return references


def build_rag_context(
    selected_evidence: list[dict[str, Any]],
) -> str:
    if not selected_evidence:
        return "검색된 직접 근거가 없습니다."

    blocks: list[str] = []

    for index, result in enumerate(selected_evidence, start=1):
        metadata = _safe_metadata(result)
        blocks.append(
            "\n".join(
                [
                    f"[근거 {index}]",
                    f"collection: {result.get('collection')}",
                    f"document_id: {result.get('document_id')}",
                    f"source_id: {result.get('source_id')}",
                    f"source_type: {result.get('source_type')}",
                    f"title: {result.get('title')}",
                    f"issue_id: {metadata.get('issue_id')}",
                    f"similarity: {float(result.get('similarity') or 0.0):.6f}",
                    f"rerank_score: {float(result.get('rerank_score') or 0.0):.6f}",
                    f"text: {_normalize_text(result.get('text'))}",
                ]
            )
        )

    return "\n\n".join(blocks)


def build_system_prompt() -> str:
    return """
너는 Law 404의 계약 진행·입주 초기 상담 보조 AI다.
사용자가 주택 임대차 계약 과정에서 지금 확인할 사실과 다음 행동을 이해하도록 돕는다.

반드시 지킬 규칙:
1. 제공된 검색 근거와 사용자 입력 안에서만 답한다.
2. 검색 근거에 없는 법률 사실, 문서 내용, 계약 상태를 만들어 내지 않는다.
3. 확인되지 않은 사실은 확인되지 않았다고 구분한다.
4. 계약이 안전하다거나 사기라고 단정하지 않는다.
5. 보증보험 가입 가능 여부와 소송 결과를 단정하지 않는다.
6. 송금·서명·잔금 지급·변경 동의처럼 되돌리기 어려운 행동은 필요한 경우 먼저 보류하도록 안내한다.
7. 사용자가 지금 할 행동은 중요도 순서로 최대 3개만 작성한다.
8. 보류할 행동이 실제로 없으면 hold_actions를 빈 배열로 둔다.
9. 추가 질문은 현재 판단을 바꿀 핵심 사실만 묻는다.
10. 이미 상담 정보에 있는 내용을 다시 묻지 않는다.
11. 일반적인 법률 설명보다 지금 해야 할 행동을 먼저 작성한다.
12. 상대방에게 확인할 문구가 도움이 될 때만 중립적인 confirmation_message를 작성한다.
13. references는 작성하지 않는다. 참고 근거는 서버 코드가 실제 검색 결과에서 별도로 붙인다.

사용 가능한 위험 수준은 아래 다섯 개뿐이다.
- 현재 입력 기준 중대한 보류 사유 미확인
- 확인 필요
- 주의 필요
- 진행 보류 권장
- 고위험 대응 전환 검토

근거 상태별 답변 원칙:
- sufficient: 직접 근거를 바탕으로 현재 판단과 행동을 안내한다.
- partial: 제한적인 임시 안내를 하고 부족한 자료와 추가 질문을 제시한다.
- insufficient: 법률 결론을 만들지 않고 확인할 자료와 필요한 보류 행동만 안내한다.
""".strip()


def build_user_prompt(
    query: str,
    consultation_context: ConsultationContext,
    evidence_status: EvidenceStatus,
    rag_context: str,
) -> str:
    return f"""
[사용자 질문]
{query}

[상담 시작 정보]
현재 계약 단계: {consultation_context.contract_stage}
대금 지급 상태: {consultation_context.payment_status}
계약 형태: {consultation_context.contract_type}
이미 확인된 사실: {json.dumps(consultation_context.known_facts, ensure_ascii=False)}

[근거 상태]
{evidence_status.value}

[검색된 근거]
{rag_context}

위 정보를 기준으로 Law 404 공통 답변 구조에 맞는 값을 작성하라.
추가 문서가 필요한 경우 현재 질문과 직접 관련 있는 자료만 작성하라.
""".strip()


def _generate_structured_answer(
    query: str,
    consultation_context: ConsultationContext,
    evidence_status: EvidenceStatus,
    selected_evidence: list[dict[str, Any]],
) -> GeneratedAnswerBody:
    api_key, chat_model = _require_openai_settings()
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError(
            "openai 패키지가 설치되지 않아 답변 생성을 실행할 수 없습니다."
        ) from error
    client = OpenAI(api_key=api_key)

    try:
        response = client.responses.parse(
            model=chat_model,
            input=[
                {
                    "role": "system",
                    "content": build_system_prompt(),
                },
                {
                    "role": "user",
                    "content": build_user_prompt(
                        query=query,
                        consultation_context=consultation_context,
                        evidence_status=evidence_status,
                        rag_context=build_rag_context(
                            selected_evidence
                        ),
                    ),
                },
            ],
            text_format=GeneratedAnswerBody,
        )
    except Exception as error:
        raise RuntimeError(
            f"A part 구조화 답변 생성 실패: {error}"
        ) from error

    parsed = response.output_parsed

    if parsed is None:
        raise RuntimeError(
            "A part 구조화 답변이 비어 있습니다. "
            "모델 응답 또는 거절 여부를 확인하세요."
        )

    return parsed



def _detect_answer_policy(
    query: str,
    consultation_context: ConsultationContext,
    search_results: list[dict[str, Any]],
) -> str | None:
    known_facts_text = " ".join(
        consultation_context.known_facts
    )
    combined = _normalize_text(
        f"{query} {known_facts_text}"
    ).lower()

    # 구체적인 상황부터 먼저 판별한다.
    if any(
        keyword in combined
        for keyword in [
            "공동명의",
            "공동소유자",
            "소유자가 두 명",
            "소유자 한 명만",
        ]
    ):
        return "co_owner"

    if (
        any(
            keyword in combined
            for keyword in [
                "등기부등본 소유자",
                "등기부 소유자",
                "소유자와 계약서",
            ]
        )
        and any(
            keyword in combined
            for keyword in [
                "임대인 이름이 다",
                "이름이 다른",
                "임대인과 소유자",
                "소유자와 임대인",
            ]
        )
    ):
        return "owner_lessor_mismatch"

    if any(
        keyword in combined
        for keyword in [
            "계좌가 바뀌",
            "계좌 변경",
            "변경된 계좌",
            "새 계좌",
        ]
    ):
        return "account_change"

    if any(
        keyword in combined
        for keyword in [
            "부동산 계좌",
            "중개사 계좌",
            "제3자 계좌",
            "계좌로 계약금",
        ]
    ):
        return "account_payment"

    if (
        any(
            keyword in combined
            for keyword in [
                "중개대상물 확인설명서",
                "확인설명서",
                "중개대상물",
            ]
        )
        and any(
            keyword in combined
            for keyword in [
                "계약서랑 다",
                "계약서와 다",
                "내용이 다",
                "불일치",
            ]
        )
    ):
        return "broker_document_mismatch"

    if any(
        keyword in combined
        for keyword in [
            "신탁등기",
            "신탁원부",
            "수탁자",
        ]
    ):
        return "trust_registry"

    if any(
        keyword in combined
        for keyword in [
            "다가구",
            "선순위 보증금이 많",
            "선순위 임차인",
        ]
    ):
        return "multiunit_priority"

    if any(
        keyword in combined
        for keyword in [
            "근저당",
            "채권최고액",
            "저당권",
        ]
    ):
        return "mortgage"

    if any(
        keyword in combined
        for keyword in [
            "압류",
            "가압류",
            "가처분",
            "가등기",
            "권리 제한",
        ]
    ):
        return "registry_restriction"

    if any(
        keyword in combined
        for keyword in [
            "집주인 아들",
            "대신 계약",
            "위임장 없이",
            "대리 권한",
            "대리인",
        ]
    ):
        return "owner_proxy"

    if (
        "전입신고" in combined
        and "대항력" in combined
    ):
        return "opposability"

    if (
        "확정일자" in combined
        and "우선변제권" in combined
    ):
        return "fixed_date_priority"

    if any(
        keyword in combined
        for keyword in [
            "집주인이 바뀌",
            "소유자가 바뀌",
            "소유자 변경",
            "새 소유자",
        ]
    ):
        return "owner_change"

    if (
        "특약" in combined
        and any(
            keyword in combined
            for keyword in [
                "계약금 반환",
                "반환 조건",
                "돌려받",
            ]
        )
    ):
        return "special_clause_return"

    if any(
        keyword in combined
        for keyword in [
            "계약서 쓴 직후",
            "계약서 작성 직후",
            "계약서를 쓴 뒤",
            "바로 해야 할 절차",
        ]
    ):
        return "after_contract_procedure"

    if any(
        keyword in combined
        for keyword in [
            "주택 임대차신고",
            "임대차신고",
            "임대차 신고",
        ]
    ):
        return "lease_report"

    if any(
        keyword in combined
        for keyword in [
            "전입세대확인서",
            "전입세대 확인서",
            "전입세대열람",
        ]
    ):
        return "household_certificate"

    if (
        "주소" in combined
        and "등기부등본" in combined
        and any(
            keyword in combined
            for keyword in [
                "다른",
                "다르면",
                "차이",
                "불일치",
            ]
        )
    ):
        return "address_mismatch"

    if (
        "계약서" in combined
        and "보증금" in combined
        and any(
            keyword in combined
            for keyword in [
                "이체 내역",
                "이체내역",
                "송금 내역",
                "금액이 다",
                "차액",
            ]
        )
    ):
        return "deposit_transfer_mismatch"

    if any(
        keyword in combined
        for keyword in [
            "전세보증금반환보증",
            "보증보험 가입 전",
            "반환보증 가입",
        ]
    ):
        return "guarantee_precheck"

    return None


def _answer_policy_payload(
    policy_id: str,
) -> dict[str, Any]:
    policies: dict[str, dict[str, Any]] = {
        "owner_proxy": {
            "risk_level": "진행 보류 권장",
            "core_judgment": (
                "실제 소유자가 아닌 사람이 계약을 진행하고 있지만, "
                "현재는 소유자의 대리 의사와 위임 범위, 계약금 수령 권한이 "
                "확인되지 않았습니다. 확인 전에는 계약서 서명과 계약금 송금을 "
                "보류하는 것이 안전합니다."
            ),
            "immediate_actions": [
                "등기부등본으로 실제 소유자를 확인합니다.",
                "소유자 본인에게 대리 계약 의사와 위임 범위를 기록이 남는 방식으로 직접 확인합니다.",
                "대리 권한 자료와 계약금 계좌 예금주·수령 권한을 함께 확인합니다.",
            ],
            "hold_actions": [
                "계약서 서명 또는 계약 진행",
                "계약금 또는 잔금 송금",
            ],
            "reasons": [
                "가족관계만으로 계약 체결 권한과 대금 수령 권한이 확인되지는 않습니다.",
                "현재는 소유자의 위임 의사와 위임 범위를 확인할 자료가 없습니다.",
            ],
            "required_information": [
                "등기부등본상 소유자 정보",
                "소유자의 대리 의사와 위임 범위를 확인할 자료",
                "대리인 신분 확인 자료",
                "계약금 계좌 예금주와 수령 권한",
            ],
            "follow_up_questions": [
                "소유자 본인과 직접 연락해 대리 계약 의사를 확인할 수 있나요?",
                "계약금을 받을 계좌의 예금주는 누구인가요?",
            ],
            "confirmation_message": (
                "소유자 본인의 대리 의사와 위임 범위, 계약금 수령 계좌를 "
                "확인할 수 있는 자료를 문자로 보내주시겠어요?"
            ),
        },
        "co_owner": {
            "risk_level": "진행 보류 권장",
            "core_judgment": (
                "공동명의 주택인데 공동소유자 한 명만 계약에 참여하고 있고, "
                "다른 공동소유자의 동의나 대리 권한이 확인되지 않았습니다. "
                "권한 범위를 확인하기 전에는 계약 진행과 계약금 송금을 보류해야 합니다."
            ),
            "immediate_actions": [
                "최신 등기부등본으로 공동소유자 전원과 각 지분을 확인합니다.",
                "계약에 나오지 않은 공동소유자의 동의 또는 대리 권한을 기록이 남는 방식으로 직접 확인합니다.",
                "계약서의 임대인 표시와 계약금 계좌 예금주가 확인된 권한 범위와 일치하는지 대조합니다.",
            ],
            "hold_actions": [
                "계약서 서명 또는 계약 진행",
                "계약금 또는 잔금 송금",
            ],
            "reasons": [
                "공동소유자 한 명이 참여했다는 사실만으로 다른 공동소유자의 계약 의사와 권한 범위가 확인되지는 않습니다.",
                "계약 권한과 대금 수령 권한을 분리하여 확인해야 합니다.",
            ],
            "required_information": [
                "최신 등기부등본과 공동소유자별 지분",
                "다른 공동소유자의 동의 또는 위임 자료",
                "계약에 참여한 사람의 신분 확인 자료",
                "계약금 계좌 예금주와 수령 권한",
            ],
            "follow_up_questions": [
                "계약에 나오지 않은 공동소유자와 직접 연락할 수 있나요?",
                "다른 공동소유자의 동의나 위임을 확인할 자료를 받았나요?",
            ],
            "confirmation_message": (
                "공동소유자 전원의 계약 의사와 현재 계약자의 대리 권한을 "
                "확인할 수 있는 자료를 보내주시겠어요?"
            ),
        },
        "owner_lessor_mismatch": {
            "risk_level": "진행 보류 권장",
            "core_judgment": (
                "등기부등본상 소유자와 계약서상 임대인이 다르지만, "
                "두 사람의 관계와 임대 권한이 확인되지 않았습니다. "
                "불일치 원인과 계약 권한을 확인하기 전에는 서명과 지급을 보류해야 합니다."
            ),
            "immediate_actions": [
                "최신 등기부등본의 소유자와 계약서의 임대인 성명·주소를 정확히 대조합니다.",
                "계약서상 임대인에게 어떤 근거로 임대 권한이 있는지 확인하고 소유자 본인에게 직접 재확인합니다.",
                "계약금 계좌 예금주와 계약 상대방의 관계 및 수령 권한을 기록으로 남깁니다.",
            ],
            "hold_actions": [
                "계약서 서명 또는 계약 진행",
                "계약금 또는 잔금 송금",
            ],
            "reasons": [
                "소유자와 계약 상대방이 다르면 임대 권한의 근거를 별도로 확인해야 합니다.",
                "임대 권한과 대금 수령 권한이 확인되지 않은 상태에서는 계약 당사자와 지급 상대방이 불명확합니다.",
            ],
            "required_information": [
                "최신 등기부등본",
                "계약서상 임대인의 신분 확인 자료",
                "소유자와 임대인의 관계를 확인할 자료",
                "임대 권한 또는 위임 범위",
                "계약금 계좌 예금주와 수령 권한",
            ],
            "follow_up_questions": [
                "계약서상 임대인과 등기부 소유자는 어떤 관계인가요?",
                "소유자 본인에게 해당 임대인의 계약 권한을 직접 확인했나요?",
            ],
            "confirmation_message": (
                "등기부 소유자와 계약서상 임대인의 관계, 임대 권한을 "
                "확인할 수 있는 자료를 보내주시겠어요?"
            ),
        },
        "account_payment": {
            "risk_level": "진행 보류 권장",
            "core_judgment": (
                "계약금을 받을 계좌가 실제 소유자 명의가 아니고, "
                "현재는 계좌 예금주와 계약 상대방의 관계 및 계약금 수령 권한이 "
                "확인되지 않았습니다. 확인 전에는 계약금 송금을 보류해야 합니다."
            ),
            "immediate_actions": [
                "등기부등본과 계약서에서 실제 소유자와 계약 상대방을 확인합니다.",
                "계좌 예금주가 누구인지 확인하고 소유자와의 관계를 기록이 남는 방식으로 받습니다.",
                "소유자 본인에게 해당 계좌의 계약금 수령 권한을 직접 확인합니다.",
            ],
            "hold_actions": [
                "계약금 송금",
            ],
            "reasons": [
                "계좌 명의가 다르다는 사실만으로 문제를 단정할 수는 없지만 수령 권한 확인 없이 송금하면 지급 근거가 불명확해질 수 있습니다.",
                "계약금은 되돌리기 어려운 지급이므로 예금주와 계약 상대방의 관계를 먼저 확인해야 합니다.",
            ],
            "required_information": [
                "계약금 계좌 예금주",
                "등기부등본상 소유자",
                "실제 계약 상대방",
                "계약금 수령 권한을 확인할 자료 또는 메시지",
            ],
            "follow_up_questions": [
                "계약금 계좌의 예금주는 누구로 표시되나요?",
                "등기부등본상 소유자 본인에게 해당 계좌의 수령 권한을 확인했나요?",
            ],
            "confirmation_message": (
                "계약금 계좌 예금주와 실제 소유자의 관계, 해당 계좌의 "
                "수령 권한을 문자로 확인해 주실 수 있을까요?"
            ),
        },
        "account_change": {
            "risk_level": "진행 보류 권장",
            "core_judgment": (
                "계약 직전에 계좌 변경 요청을 받았지만, 변경 요청이 소유자 본인의 "
                "의사인지와 새 계좌 예금주의 계약금 수령 권한이 확인되지 않았습니다. "
                "확인 전에는 송금을 보류해야 합니다."
            ),
            "immediate_actions": [
                "기존에 확인한 연락처로 소유자 본인에게 계좌 변경 요청의 진위를 직접 확인합니다.",
                "기존 계좌와 바뀐 계좌의 예금주를 대조하고 변경 이유와 수령 권한을 서면이나 문자로 받습니다.",
                "계약서 또는 별도 확인서에 최종 지급 계좌와 변경 근거를 기록합니다.",
            ],
            "hold_actions": [
                "계약금 또는 잔금 송금",
            ],
            "reasons": [
                "갑작스러운 계좌 변경은 지급 상대방을 다시 확인해야 하는 상황입니다.",
                "소유자 본인의 의사와 새 예금주의 수령 권한이 확인되어야 지급 근거를 남길 수 있습니다.",
            ],
            "required_information": [
                "기존 계좌와 변경된 계좌의 예금주",
                "소유자 본인의 계좌 변경 확인",
                "계좌 변경 이유",
                "새 계좌의 계약금 수령 권한",
                "변경 요청이 남아 있는 문자 또는 확인서",
            ],
            "follow_up_questions": [
                "소유자 본인에게 기존 연락처로 계좌 변경 사실을 확인했나요?",
                "새 계좌 예금주는 누구이며 소유자와 어떤 관계인가요?",
            ],
            "confirmation_message": (
                "계좌 변경 이유와 새 예금주의 수령 권한을 소유자 본인이 "
                "확인한 문자나 확인서를 보내주시겠어요?"
            ),
        },
        "broker_document_mismatch": {
            "risk_level": "진행 보류 권장",
            "core_judgment": (
                "중개대상물 확인설명서와 계약서 사이에 불일치가 있으므로, "
                "어느 내용이 정확한지 대조하고 정정하기 전에는 계약서 서명을 보류해야 합니다."
            ),
            "immediate_actions": [
                "두 문서의 주소·소유자·권리관계·보증금·관리비·시설 상태를 항목별로 대조합니다.",
                "공인중개사와 임대인에게 불일치 원인과 정확한 내용을 설명하도록 요청합니다.",
                "설명 결과를 반영한 계약서와 중개대상물 확인설명서를 다시 받아 정정 여부를 확인합니다.",
            ],
            "hold_actions": [
                "정정 전 계약서 서명 또는 계약 진행",
            ],
            "reasons": [
                "확인설명서와 계약서는 계약 대상과 주요 조건을 확인하는 서로 다른 문서입니다.",
                "불일치를 설명만 듣고 넘기면 실제 계약 조건과 확인받은 사실이 달라질 수 있습니다.",
            ],
            "required_information": [
                "중개대상물 확인설명서",
                "계약서",
                "불일치 항목 목록",
                "공인중개사와 임대인의 설명",
                "정정된 최종 문서",
            ],
            "follow_up_questions": [
                "두 문서에서 정확히 어떤 항목이 다르게 적혀 있나요?",
                "공인중개사가 정정된 문서를 다시 제공하기로 했나요?",
            ],
            "confirmation_message": (
                "확인설명서와 계약서의 불일치 항목, 정정 내용을 "
                "문서로 다시 정리해 주실 수 있을까요?"
            ),
        },
        "mortgage": {
            "risk_level": "진행 보류 권장",
            "core_judgment": (
                "근저당이 있다는 사실만으로 계약 가능 여부를 단정할 수는 없지만, "
                "채권최고액·실제 채무액·전세보증금·주택가액과 다른 선순위 권리를 "
                "함께 확인하기 전에는 계약 진행을 보류해야 합니다."
            ),
            "immediate_actions": [
                "최신 등기부등본에서 근저당권자·채권최고액·설정일과 다른 권리관계를 확인합니다.",
                "주택가액 또는 시세와 전세보증금, 확인 가능한 선순위 권리 금액을 함께 정리합니다.",
                "말소 조건이나 잔금일 권리관계 확인 방법을 계약서 특약과 지급 절차에 명확히 반영합니다.",
            ],
            "hold_actions": [
                "확인 전 계약서 서명 또는 계약 진행",
                "계약금 또는 잔금 송금",
            ],
            "reasons": [
                "채권최고액과 실제 채무액은 다를 수 있으므로 등기 표시만으로 안전 여부를 단정할 수 없습니다.",
                "전세보증금과 선순위 권리의 합계가 주택가액에서 차지하는 범위를 함께 봐야 합니다.",
            ],
            "required_information": [
                "최신 등기부등본",
                "근저당 채권최고액과 확인 가능한 실제 채무액",
                "전세보증금",
                "주택가액 또는 시세 자료",
                "다른 선순위 권리",
                "말소 계획 또는 특약",
            ],
            "follow_up_questions": [
                "등기부등본의 채권최고액과 전세보증금은 각각 얼마인가요?",
                "주택가액과 다른 선순위 권리를 확인할 자료가 있나요?",
            ],
            "confirmation_message": None,
        },
        "multiunit_priority": {
            "risk_level": "진행 보류 권장",
            "core_judgment": (
                "다가구주택은 다른 세대의 선순위 보증금이 함께 영향을 줄 수 있으므로, "
                "선순위 임차보증금 총액과 등기부 권리관계, 주택가액을 확인하기 전에는 "
                "계약 진행을 보류하는 것이 안전합니다."
            ),
            "immediate_actions": [
                "최신 등기부등본으로 근저당·압류 등 권리관계를 확인합니다.",
                "확인 가능한 자료를 통해 기존 전입세대와 선순위 보증금 총액을 파악합니다.",
                "주택가액 또는 시세와 선순위 권리·선순위 보증금·내 보증금을 함께 비교합니다.",
            ],
            "hold_actions": [
                "확인 전 계약서 서명 또는 계약 진행",
                "계약금 또는 잔금 송금",
            ],
            "reasons": [
                "다가구주택은 건물 전체를 기준으로 다른 세대의 선순위 임차권이 보증금 회수에 영향을 줄 수 있습니다.",
                "선순위 보증금과 권리관계를 주택가액과 함께 보지 않으면 위험 범위를 판단하기 어렵습니다.",
            ],
            "required_information": [
                "최신 등기부등본",
                "기존 전입세대 관련 확인 자료",
                "선순위 보증금 총액",
                "근저당 등 선순위 권리",
                "주택가액 또는 시세",
                "내 전세보증금",
            ],
            "follow_up_questions": [
                "다른 세대의 선순위 보증금 총액을 확인했나요?",
                "주택가액과 등기부 권리관계를 확인할 자료가 있나요?",
            ],
            "confirmation_message": None,
        },
        "registry_restriction": {
            "risk_level": "진행 보류 권장",
            "core_judgment": (
                "등기부등본에 압류·가압류 등 권리 제한 표시가 확인됐지만, "
                "현재는 말소 여부와 실제 계약에 미치는 영향이 확인되지 않았습니다. "
                "권리관계를 확인하기 전에는 계약 진행과 대금 지급을 보류하는 것이 안전합니다."
            ),
            "immediate_actions": [
                "최신 등기부등본에서 권리자·접수일자·원인과 현재 말소 여부를 확인합니다.",
                "임대인과 공인중개사에게 권리 제한의 원인·해소 계획·말소 확인 시점을 기록으로 요청합니다.",
                "보증금과 선순위 권리를 함께 검토할 자료를 확보하고 필요하면 공식 기관이나 전문가에게 확인합니다.",
            ],
            "hold_actions": [
                "계약서 서명 또는 계약 진행",
                "계약금 또는 잔금 송금",
            ],
            "reasons": [
                "압류·가압류 표시는 계약 전 추가 확인이 필요한 권리관계 위험 신호입니다.",
                "표시만으로 계약 가능 여부나 법적 효력을 단정할 수 없으므로 말소 여부와 보증금 보호에 미치는 영향을 함께 확인해야 합니다.",
            ],
            "required_information": [
                "최신 등기부등본",
                "권리자·접수일자·원인",
                "말소 여부 또는 해소 계획",
                "보증금과 선순위 권리 자료",
            ],
            "follow_up_questions": [
                "현재 등기부등본은 언제 발급한 문서인가요?",
                "임대인에게 말소 계획과 확인 자료를 받았나요?",
            ],
            "confirmation_message": (
                "권리 제한의 원인과 말소 계획, 말소 완료를 확인할 자료를 "
                "문자로 정리해 주실 수 있을까요?"
            ),
        },
        "trust_registry": {
            "risk_level": "진행 보류 권장",
            "core_judgment": (
                "신탁등기가 있는 주택은 계약 상대방이 임대인이라고 주장하더라도, "
                "신탁원부상 수탁자와 임대 권한·동의 조건을 확인해야 합니다. "
                "권한 확인 전에는 계약과 송금을 보류해야 합니다."
            ),
            "immediate_actions": [
                "최신 등기부등본과 신탁원부를 확인해 수탁자와 신탁 내용을 파악합니다.",
                "현재 계약 상대방에게 임대 권한이 있는지와 수탁자 동의가 필요한지를 확인합니다.",
                "계약금 계좌 예금주와 수령 권한이 신탁 관계 및 확인된 계약 권한과 일치하는지 대조합니다.",
            ],
            "hold_actions": [
                "계약서 서명 또는 계약 진행",
                "계약금 또는 잔금 송금",
            ],
            "reasons": [
                "신탁등기에서는 등기상 권리자와 실제 계약 권한을 신탁원부까지 확인해야 할 수 있습니다.",
                "임대 권한과 대금 수령 권한이 확인되지 않으면 계약 상대방의 권한을 판단하기 어렵습니다.",
            ],
            "required_information": [
                "최신 등기부등본",
                "신탁원부",
                "수탁자 정보",
                "임대 권한 또는 수탁자 동의 자료",
                "계약금 계좌와 수령 권한",
            ],
            "follow_up_questions": [
                "신탁원부를 확인했나요?",
                "수탁자 또는 신탁계약에서 인정한 임대 권한 자료를 받았나요?",
            ],
            "confirmation_message": (
                "신탁원부와 수탁자의 임대 동의 또는 계약 권한을 "
                "확인할 수 있는 자료를 보내주시겠어요?"
            ),
        },
        "opposability": {
            "risk_level": "확인 필요",
            "core_judgment": (
                "대항력은 전입신고만으로 바로 생기는 것이 아니라, "
                "주택 인도인 실제 입주와 주민등록인 전입신고를 모두 갖춘 뒤 "
                "원칙적으로 그 다음 날부터 발생하는 구조로 확인해야 합니다."
            ),
            "immediate_actions": [
                "실제 입주일과 전입신고 예정일을 함께 확인합니다.",
                "입주한 날 전입신고를 처리하고 접수 결과를 보관합니다.",
                "잔금 지급 전후의 최신 등기부등본을 확인해 권리관계 변동 여부를 기록합니다.",
            ],
            "hold_actions": [],
            "reasons": [
                "대항력 판단에는 주택 인도와 주민등록 요건이 함께 필요합니다.",
                "전입신고를 했다는 사실만으로 실제 입주 요건까지 자동으로 확인되지는 않습니다.",
            ],
            "required_information": [
                "실제 입주일",
                "전입신고일과 접수 결과",
                "잔금 지급일",
                "최신 등기부등본",
            ],
            "follow_up_questions": [
                "실제 입주 예정일과 전입신고 예정일은 같은 날인가요?",
            ],
            "confirmation_message": None,
        },
        "fixed_date_priority": {
            "risk_level": "확인 필요",
            "core_judgment": (
                "확정일자만 받았다고 우선변제권 요건이 모두 갖춰지는 것은 아닙니다. "
                "확정일자와 함께 주택 인도인 실제 입주, 주민등록인 전입신고 등 "
                "대항요건을 갖췄는지 확인해야 합니다."
            ),
            "immediate_actions": [
                "확정일자 부여 여부와 계약서의 주요 기재사항을 확인합니다.",
                "실제 입주와 전입신고 시점을 함께 정리해 대항요건 충족 시점을 확인합니다.",
                "잔금 지급 전후 최신 등기부등본과 접수 기록을 보관합니다.",
            ],
            "hold_actions": [],
            "reasons": [
                "우선변제권은 확정일자 하나만 떼어 판단하기보다 대항요건과 함께 확인해야 합니다.",
                "아직 입주와 전입신고 전이라면 확정일자만으로 보호 요건이 완성됐다고 단정할 수 없습니다.",
            ],
            "required_information": [
                "확정일자부 계약서",
                "실제 입주일",
                "전입신고일",
                "잔금 지급일",
                "최신 등기부등본",
            ],
            "follow_up_questions": [
                "현재 실제 입주와 전입신고까지 완료했나요?",
            ],
            "confirmation_message": None,
        },
        "owner_change": {
            "risk_level": "확인 필요",
            "core_judgment": (
                "계약 후 소유자 변경이 있었다면 최신 등기부등본으로 새 소유자를 확인하고, "
                "현재 임대차가 대항요건을 갖췄는지에 따라 새 소유자의 임대인 지위와 "
                "보증금 반환 관계를 확인해야 합니다."
            ),
            "immediate_actions": [
                "최신 등기부등본으로 소유권 이전일과 새 소유자 정보를 확인합니다.",
                "실제 입주와 전입신고 등 대항력 요건을 언제 갖췄는지 정리합니다.",
                "새 소유자에게 계약 승계와 보증금 반환 관련 연락처·지급 계좌 변경 여부를 서면으로 확인합니다.",
            ],
            "hold_actions": [],
            "reasons": [
                "소유자 변경만으로 보증금 반환 관계를 단정하기보다 임대차의 대항력 요건과 소유권 이전 시점을 함께 확인해야 합니다.",
                "새 소유자 정보와 계약 승계 관계를 기록해 두어야 이후 연락과 보증금 반환 요청의 상대방을 확인할 수 있습니다.",
            ],
            "required_information": [
                "최신 등기부등본",
                "소유권 이전일",
                "새 소유자 정보",
                "입주일과 전입신고일",
                "기존 임대차계약서",
            ],
            "follow_up_questions": [
                "현재 실제 입주와 전입신고를 유지하고 있나요?",
                "최신 등기부등본에서 새 소유자를 확인했나요?",
            ],
            "confirmation_message": None,
        },
        "special_clause_return": {
            "risk_level": "진행 보류 권장",
            "core_judgment": (
                "계약금 반환 특약의 문구와 발동 조건이 모호하므로, "
                "반환 사유·범위·기한·방법을 서면으로 명확히 정정하기 전에는 "
                "계약서 서명과 계약금 송금을 보류해야 합니다."
            ),
            "immediate_actions": [
                "특약 원문에서 계약금 반환이 적용되는 구체적인 조건과 제외 사유를 확인합니다.",
                "반환 금액·반환 기한·반환 방법·필요한 증빙을 문구로 명확히 작성합니다.",
                "임대인과 공인중개사가 동의한 최종 특약을 계약서에 반영하고 서명 전 다시 확인합니다.",
            ],
            "hold_actions": [
                "특약 정정 전 계약서 서명 또는 계약 진행",
                "계약금 송금",
            ],
            "reasons": [
                "계약금 반환 여부는 실제 특약 문구와 발생한 상황에 따라 달라질 수 있습니다.",
                "구두 설명이 아니라 계약서에 남은 문구와 기록으로 조건을 확인해야 합니다.",
            ],
            "required_information": [
                "현재 특약 원문",
                "계약금 반환 사유",
                "반환 범위와 금액",
                "반환 기한과 방법",
                "필요한 증빙",
                "당사자가 동의한 정정 문구",
            ],
            "follow_up_questions": [
                "현재 특약 문구를 그대로 확인할 수 있나요?",
                "어떤 상황에서 계약금을 반환받으려는 조건인가요?",
            ],
            "confirmation_message": (
                "계약금 반환 사유·금액·기한·방법이 보이도록 "
                "특약 문구를 서면으로 다시 작성해 주실 수 있을까요?"
            ),
        },
        "after_contract_procedure": {
            "risk_level": "현재 입력 기준 중대한 보류 사유 미확인",
            "core_judgment": (
                "계약서를 작성한 직후에는 계약서와 계약금 지급 기록을 먼저 보관하고, "
                "잔금 전 권리관계 재확인과 입주일의 전입신고·확정일자 등 "
                "보증금 보호 절차를 순서대로 준비해야 합니다."
            ),
            "immediate_actions": [
                "서명·날인된 계약서 원본과 계약금 이체 내역·영수증·송금 요청 메시지를 함께 보관합니다.",
                "계약서 주요 내용과 잔금일·입주일을 확인하고 잔금 전 최신 등기부등본을 재확인할 일정을 잡습니다.",
                "주택 임대차신고 대상 여부를 확인하고 입주일의 전입신고·확정일자에 필요한 서류와 순서를 준비합니다.",
            ],
            "hold_actions": [],
            "reasons": [
                "계약서와 지급 기록은 계약 내용과 계약금 지급 사실을 확인하는 기본 자료입니다.",
                "계약서 작성 뒤에도 잔금일까지 권리관계가 바뀔 수 있어 최신 등기부등본 재확인이 필요합니다.",
                "전입신고·확정일자·임대차신고는 계약 상태와 처리 시점에 맞춰 준비해야 합니다.",
            ],
            "required_information": [
                "서명·날인된 계약서 원본",
                "계약금 이체 내역 또는 영수증",
                "잔금일과 입주 예정일",
                "최신 등기부등본",
                "주택 임대차신고 대상과 처리 여부",
                "전입신고·확정일자 준비 서류",
            ],
            "follow_up_questions": [
                "잔금일과 실제 입주 예정일은 언제인가요?",
                "계약서 원본과 계약금 이체 내역을 모두 보관하고 있나요?",
            ],
            "confirmation_message": None,
        },
        "lease_report": {
            "risk_level": "확인 필요",
            "core_judgment": (
                "주택 임대차신고는 모든 계약을 같은 방식으로 단정하기보다 "
                "지역·계약 금액·계약 유형에 따른 신고 대상 여부를 먼저 확인해야 합니다. "
                "신고 대상이면 계약 체결일을 기준으로 신고 기한과 처리 방법을 확인해야 합니다."
            ),
            "immediate_actions": [
                "계약 주소·보증금·월세·계약 체결일을 기준으로 주택 임대차신고 대상 여부를 확인합니다.",
                "신고 대상이면 계약 체결일로부터 30일 이내 처리 기준을 공식 신고 시스템이나 관할 주민센터에서 재확인합니다.",
                "신고 완료 후 신고필증 또는 접수 결과를 계약서와 함께 보관합니다.",
            ],
            "hold_actions": [],
            "reasons": [
                "주택 임대차신고 의무는 계약 조건과 적용 지역 등 신고 대상 기준을 확인해야 합니다.",
                "대상 계약은 정해진 기한 안에 처리하고 접수 결과를 남겨야 합니다.",
            ],
            "required_information": [
                "계약 주소",
                "계약 체결일",
                "보증금과 월세",
                "신규·갱신 계약 여부",
                "공식 신고 시스템 또는 관할 주민센터 안내",
                "신고필증 또는 접수 결과",
            ],
            "follow_up_questions": [
                "계약 체결일과 보증금·월세는 어떻게 되나요?",
                "관할 주민센터나 공식 신고 시스템에서 대상 여부를 확인했나요?",
            ],
            "confirmation_message": None,
        },
        "household_certificate": {
            "risk_level": "확인 필요",
            "core_judgment": (
                "전입세대확인서는 계약 전 기존 전입세대와 점유 상태를 확인하고, "
                "잔금 전에도 변동 여부를 다시 확인하는 자료로 활용해야 합니다. "
                "선순위 임차인 위험은 다른 권리관계 자료와 함께 봐야 합니다."
            ),
            "immediate_actions": [
                "계약 전 전입세대확인서에서 기존 전입세대와 세대주 현황을 확인합니다.",
                "잔금 지급 전 다시 확인해 계약 이후 전입세대나 점유 상태가 바뀌었는지 대조합니다.",
                "등기부등본과 선순위 보증금 관련 자료를 함께 확인해 우선순위 위험을 정리합니다.",
            ],
            "hold_actions": [],
            "reasons": [
                "전입세대 현황은 기존 점유자와 선순위 가능성을 확인하는 자료 중 하나입니다.",
                "계약 전 확인 뒤 잔금일까지 상태가 바뀔 수 있어 잔금 전 재확인이 필요합니다.",
            ],
            "required_information": [
                "계약 전 전입세대확인서",
                "잔금 전 최신 전입세대확인서",
                "최신 등기부등본",
                "기존 전입세대와 점유 상태",
                "선순위 보증금 관련 확인 자료",
            ],
            "follow_up_questions": [
                "계약 전 전입세대확인서를 확인했나요?",
                "잔금일은 언제이며 잔금 전 재확인할 수 있나요?",
            ],
            "confirmation_message": None,
        },
        "address_mismatch": {
            "risk_level": "진행 보류 권장",
            "core_judgment": (
                "계약서 주소와 등기부등본 주소가 다르므로 단순 오기로 넘기지 말고, "
                "지번·도로명·건물명·동·호수를 대조해 같은 목적물인지 확인해야 합니다. "
                "일치 여부 확인 전에는 서명과 송금을 보류해야 합니다."
            ),
            "immediate_actions": [
                "계약서와 등기부등본의 지번·도로명·건물명·동·호수를 항목별로 대조합니다.",
                "건축물대장이나 현장 표시와 비교해 실제 계약 목적물이 같은지 확인합니다.",
                "오류라면 임대인과 공인중개사에게 계약서 주소를 정정받고 최종 문서를 다시 확인합니다.",
            ],
            "hold_actions": [
                "주소 정정 전 계약서 서명 또는 계약 진행",
                "계약금 또는 잔금 송금",
            ],
            "reasons": [
                "주소 불일치는 다른 호실이나 다른 목적물을 계약하는 문제로 이어질 수 있습니다.",
                "계약 목적물은 계약서와 공적 장부에서 서로 식별될 수 있어야 합니다.",
            ],
            "required_information": [
                "계약서 주소",
                "등기부등본 주소",
                "지번과 도로명",
                "건물명과 동·호수",
                "건축물대장 또는 현장 표시",
                "정정된 계약서",
            ],
            "follow_up_questions": [
                "주소 중 지번·도로명·동·호수 가운데 어느 부분이 다른가요?",
                "건축물대장이나 현장 표시와 대조했나요?",
            ],
            "confirmation_message": (
                "계약서와 등기부등본의 지번·도로명·동·호수가 "
                "같은 목적물을 가리키는지 확인해 주시겠어요?"
            ),
        },
        "deposit_transfer_mismatch": {
            "risk_level": "주의 필요",
            "core_judgment": (
                "계약서 보증금과 이체 내역 금액 사이에 차액이 있고 "
                "지급 일자·수령인·차액 원인이 정리되지 않았습니다. "
                "금액 불일치를 정정하기 전에는 추가 송금이나 잔금 지급을 보류해야 합니다."
            ),
            "immediate_actions": [
                "계약서의 보증금·계약금·중도금·잔금과 실제 이체 내역 합계를 항목별로 대조합니다.",
                "각 지급의 일자·수령 계좌·예금주·영수증 또는 수령 확인을 정리합니다.",
                "차액 원인을 임대인과 확인하고 계약서나 별도 정산 확인서에 정정 내용을 남깁니다.",
            ],
            "hold_actions": [
                "차액 확인 전 추가 송금 또는 잔금 지급",
            ],
            "reasons": [
                "계약서와 지급 기록이 다르면 실제 지급액과 남은 금액을 정확히 판단하기 어렵습니다.",
                "추가 지급 전에 수령인과 금액을 서면으로 정리해야 이중 지급이나 정산 분쟁을 줄일 수 있습니다.",
            ],
            "required_information": [
                "계약서상 보증금과 지급 일정",
                "전체 이체 내역",
                "수령 계좌와 예금주",
                "영수증 또는 수령 확인",
                "차액 계산표",
                "정정된 계약서 또는 정산 확인서",
            ],
            "follow_up_questions": [
                "계약서상 총보증금과 현재까지 이체한 합계는 각각 얼마인가요?",
                "각 이체의 수령 계좌와 예금주를 확인했나요?",
            ],
            "confirmation_message": (
                "계약서 금액과 실제 이체 합계, 남은 잔금을 표로 정리해 "
                "임대인과 서면 확인해 주실 수 있을까요?"
            ),
        },
        "guarantee_precheck": {
            "risk_level": "확인 필요",
            "core_judgment": (
                "전세보증금반환보증의 실제 가입 가능 여부는 계약 내용, "
                "주택 가격과 권리관계, 신청 시점, 제출 서류 등을 보증기관이 "
                "심사한 뒤 결정합니다. 현재 단계에서는 가입 가능 여부를 단정하지 말고 "
                "공식 상품안내와 심사 기준을 확인해야 합니다."
            ),
            "immediate_actions": [
                "보증기관의 최신 상품안내에서 가입 대상·신청 가능 기간·보증 한도·심사 절차를 확인합니다.",
                "임대차계약서·확정일자·보증금 지급 기록·등기부등본상 소유자와 권리관계를 확인합니다.",
                "보증기관의 최신 제출 서류 목록에 따라 계약서·지급 증빙·주민등록 관련 서류를 준비합니다.",
            ],
            "hold_actions": [],
            "reasons": [
                "보증 가입 여부는 한 가지 서류만으로 결정되지 않고 보증기관의 공식 심사를 거쳐야 합니다.",
                "주택 가격과 선순위 권리, 계약 내용, 신청 시점과 제출 서류에 따라 심사 결과가 달라질 수 있습니다.",
            ],
            "required_information": [
                "신청하려는 보증기관과 보증 상품",
                "계약 시작일과 종료일",
                "전세보증금과 주택 유형",
                "확정일자부 임대차계약서",
                "보증금 지급 증빙",
                "최신 등기부등본과 제출 서류 목록",
            ],
            "follow_up_questions": [
                "어느 보증기관의 반환보증을 신청할 예정인가요?",
                "계약 시작일·종료일과 전세보증금은 어떻게 되나요?",
            ],
            "confirmation_message": None,
        },
    }

    return policies.get(policy_id, {})


def _apply_server_side_safety_rules(
    query: str,
    generated: GeneratedAnswerBody,
    evidence_status: EvidenceStatus,
    consultation_context: ConsultationContext,
    search_results: list[dict[str, Any]],
) -> GeneratedAnswerBody:
    data = generated.model_dump()

    data["immediate_actions"] = data["immediate_actions"][:3]
    data["hold_actions"] = data["hold_actions"][:3]
    data["reasons"] = data["reasons"][:4]
    data["required_information"] = data["required_information"][:6]
    data["follow_up_questions"] = data["follow_up_questions"][:3]

    policy_id = _detect_answer_policy(
        query=query,
        consultation_context=consultation_context,
        search_results=search_results,
    )

    if policy_id:
        policy_payload = _answer_policy_payload(policy_id)

        if policy_payload:
            data.update(policy_payload)

    elif evidence_status == EvidenceStatus.INSUFFICIENT:
        data["risk_level"] = "확인 필요"

    return GeneratedAnswerBody.model_validate(data)


def _search_code_version(search_results: list[dict[str, Any]]) -> str | None:
    if not search_results:
        return None
    return _normalize_text(search_results[0].get("code_version")) or None


def _validate_grounded_response(response: APartRAGResponse) -> None:
    if response.search_result_count <= 0:
        raise RAGAnswerValidationError("검색 결과가 없는 답변은 완료 상태로 반환할 수 없습니다.")
    if not response.selected_evidence or not response.answer.references:
        raise RAGAnswerValidationError(
            "선택 근거와 references가 없는 답변은 완료 상태로 반환할 수 없습니다.",
            search_result_count=response.search_result_count,
            search_code_version=response.search_code_version,
        )
    if response.evidence_status == EvidenceStatus.INSUFFICIENT:
        raise RAGAnswerValidationError(
            "근거 상태가 insufficient인 답변은 생성 완료로 반환할 수 없습니다.",
            search_result_count=response.search_result_count,
            search_code_version=response.search_code_version,
        )
    selected_ids = {item.evidence_id for item in response.selected_evidence}
    reference_ids = {item.evidence_id for item in response.answer.references}
    if not reference_ids.issubset(selected_ids):
        raise RAGAnswerValidationError(
            "답변 references가 선택된 RAG 근거와 일치하지 않습니다.",
            search_result_count=response.search_result_count,
            search_code_version=response.search_code_version,
        )
    if not response.answer.core_judgment.strip():
        raise RAGAnswerValidationError(
            "핵심 판단이 비어 있습니다.",
            search_result_count=response.search_result_count,
            search_code_version=response.search_code_version,
        )


def answer_with_rag(
    query: str,
    consultation_context: ConsultationContext | None = None,
    collections: list[str] | None = None,
    search_top_k: int = 8,
    answer_evidence_count: int = 5,
    min_similarity: float = 0.30,
    candidate_k: int = 80,
) -> APartRAGResponse:
    """근거가 충분할 때만 LLM 답변을 생성하는 strict 함수다."""

    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query는 빈 문자열일 수 없습니다.")
    context = consultation_context or ConsultationContext()

    try:
        search_results = search_documents(
            query=normalized_query,
            top_k=search_top_k,
            collections=collections,
            min_similarity=min_similarity,
            candidate_k=candidate_k,
        )
    except Exception as error:
        raise RAGSearchUnavailableError(
            f"RAG 검색 실행에 실패했습니다: {error}"
        ) from error

    search_code_version = _search_code_version(search_results)
    if not search_results:
        raise RAGEvidenceNotFoundError(
            "RAG 검색 결과가 없어 답변 생성을 중단했습니다.",
            search_result_count=0,
            search_code_version=search_code_version,
        )

    selected_evidence = select_answer_evidence(
        query=normalized_query,
        search_results=search_results,
        max_items=answer_evidence_count,
    )
    if not selected_evidence:
        raise RAGEvidenceNotFoundError(
            "검색 결과 중 답변에 사용할 수 있는 근거를 선택하지 못했습니다.",
            search_result_count=len(search_results),
            search_code_version=search_code_version,
        )

    evidence_status = determine_evidence_status(
        query=normalized_query,
        selected_evidence=selected_evidence,
        search_results=search_results,
    )
    if evidence_status == EvidenceStatus.INSUFFICIENT:
        raise RAGEvidenceInsufficientError(
            "검색 결과는 있으나 질문에 직접 답할 근거가 부족해 답변 생성을 중단했습니다.",
            search_result_count=len(search_results),
            search_code_version=search_code_version,
        )

    try:
        generated = _generate_structured_answer(
            query=normalized_query,
            consultation_context=context,
            evidence_status=evidence_status,
            selected_evidence=selected_evidence,
        )
    except Exception as error:
        raise RAGAnswerGenerationError(
            f"근거 기반 답변 생성에 실패했습니다: {error}",
            search_result_count=len(search_results),
            search_code_version=search_code_version,
        ) from error

    generated = _apply_server_side_safety_rules(
        query=normalized_query,
        generated=generated,
        evidence_status=evidence_status,
        consultation_context=context,
        search_results=search_results,
    )
    references = _build_reference_items(selected_evidence)
    answer = APartAnswer(
        risk_level=generated.risk_level,
        core_judgment=generated.core_judgment,
        immediate_actions=generated.immediate_actions,
        hold_actions=generated.hold_actions,
        reasons=generated.reasons,
        required_information=generated.required_information,
        references=references,
        follow_up_questions=generated.follow_up_questions,
        confirmation_message=generated.confirmation_message,
    )
    response = APartRAGResponse(
        query=normalized_query,
        answer_code_version=ANSWER_CODE_VERSION,
        consultation_context=context,
        evidence_status=evidence_status,
        generation_status=(
            RAGGenerationStatus.PARTIAL_EVIDENCE
            if evidence_status == EvidenceStatus.PARTIAL
            else RAGGenerationStatus.COMPLETED
        ),
        answer=answer,
        selected_evidence=references,
        search_result_count=len(search_results),
        search_code_version=search_code_version,
    )
    _validate_grounded_response(response)
    return response


def _guarded_failure_response(
    *,
    query: str,
    context: ConsultationContext,
    error: RAGExecutionError,
) -> APartRAGResponse:
    status = error.generation_status
    if status == RAGGenerationStatus.SEARCH_FAILED:
        judgment = "RAG 검색 자체가 실패해 근거 기반 결론을 생성하지 않았습니다."
        action = "잠시 후 같은 질문으로 근거 검색을 다시 실행합니다."
    elif status == RAGGenerationStatus.EVIDENCE_NOT_FOUND:
        judgment = "검증 가능한 RAG 근거를 찾지 못해 근거 기반 결론을 생성하지 않았습니다."
        action = "질문의 핵심 사실과 문서 상태를 더 구체적으로 확인한 뒤 다시 검색합니다."
    elif status == RAGGenerationStatus.GENERATION_FAILED:
        judgment = "검색 근거는 확인했지만 답변 생성이 실패해 결론을 반환하지 않았습니다."
        action = "동일한 선택 근거로 답변 생성을 다시 시도합니다."
    else:
        judgment = "생성된 답변의 근거 연결을 검증하지 못해 결론을 반환하지 않았습니다."
        action = "검색 근거와 답변 references를 다시 검증합니다."

    return APartRAGResponse(
        query=query,
        answer_code_version=ANSWER_CODE_VERSION,
        consultation_context=context,
        evidence_status=EvidenceStatus.INSUFFICIENT,
        generation_status=status,
        answer=APartAnswer(
            risk_level="확인 필요",
            core_judgment=judgment,
            immediate_actions=[action],
            hold_actions=[],
            reasons=[str(error)],
            required_information=["질문과 직접 연결되는 공식 근거"],
            references=[],
            follow_up_questions=[],
            confirmation_message=None,
        ),
        selected_evidence=[],
        search_result_count=error.search_result_count,
        search_code_version=error.search_code_version,
        warnings=[str(error)],
    )


def answer_with_rag_guarded(
    query: str,
    consultation_context: ConsultationContext | None = None,
    **options: Any,
) -> APartRAGResponse:
    """검색 실패·근거 부족을 구조화해 반환하되 법률 결론은 만들지 않는다."""

    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query는 빈 문자열일 수 없습니다.")
    if consultation_context is None:
        context = ConsultationContext()
    elif isinstance(consultation_context, ConsultationContext):
        context = consultation_context
    elif hasattr(consultation_context, "model_dump"):
        context = ConsultationContext.model_validate(
            consultation_context.model_dump(mode="python")
        )
    else:
        context = ConsultationContext.model_validate(consultation_context)
    try:
        return answer_with_rag(
            query=normalized_query,
            consultation_context=context,
            **options,
        )
    except RAGExecutionError as error:
        return _guarded_failure_response(
            query=normalized_query,
            context=context,
            error=error,
        )


def format_answer_for_console(response: APartRAGResponse) -> str:
    answer = response.answer
    lines = [
        "=" * 100,
        f"질문: {response.query}",
        f"답변 코드 버전: {response.answer_code_version}",
        f"검색 코드 버전: {response.search_code_version}",
        f"검색 결과 수: {response.search_result_count}",
        f"선택 근거 수: {len(response.selected_evidence)}",
        f"근거 상태: {response.evidence_status.value}",
        f"생성 상태: {response.generation_status.value}",
        "-" * 100,
    ]

    if answer.document_summary is not None:
        lines.append("문서 요약")
        for section in answer.document_summary.sections:
            lines.append(f"[{section.title}]")
            if section.items:
                lines.extend(f"- {item}" for item in section.items)
            else:
                lines.append("- 확인된 내용 없음")
        if answer.document_summary.warnings:
            lines.append("[확인 필요]")
            lines.extend(f"- {item}" for item in answer.document_summary.warnings)
        lines.append("")

    lines.extend([
        f"위험 수준\n→ {answer.risk_level}",
        "",
        f"핵심 판단\n→ {answer.core_judgment}",
        "",
        "지금 해야 할 행동",
    ])

    if answer.immediate_actions:
        lines.extend(
            f"{index}. {item}"
            for index, item in enumerate(
                answer.immediate_actions,
                start=1,
            )
        )
    else:
        lines.append("→ 없음")

    lines.extend(["", "우선 보류해야 할 행동"])

    if answer.hold_actions:
        lines.extend(
            f"{index}. {item}"
            for index, item in enumerate(
                answer.hold_actions,
                start=1,
            )
        )
    else:
        lines.append("→ 없음")

    lines.extend(["", "판단 이유"])
    lines.extend(
        f"{index}. {item}"
        for index, item in enumerate(answer.reasons, start=1)
    )

    lines.extend(["", "추가 확인 정보·문서"])
    if answer.required_information:
        lines.extend(
            f"{index}. {item}"
            for index, item in enumerate(
                answer.required_information,
                start=1,
            )
        )
    else:
        lines.append("→ 없음")

    lines.extend(["", "추가 질문"])
    if answer.follow_up_questions:
        lines.extend(
            f"{index}. {item}"
            for index, item in enumerate(
                answer.follow_up_questions,
                start=1,
            )
        )
    else:
        lines.append("→ 없음")

    if answer.confirmation_message:
        lines.extend(
            [
                "",
                "상대방에게 요청할 확인 문구",
                f"→ {answer.confirmation_message}",
            ]
        )

    lines.extend(["", "법률 근거·참고 자료"])
    if not answer.references:
        lines.append("→ 현재 검색 결과에서 질문에 직접 답하는 본문 근거를 찾지 못했습니다.")

    for reference in answer.references:
        lines.extend(
            [
                f"[{reference.evidence_id}] "
                f"{reference.title or reference.document_id}",
                f"collection: {reference.collection}",
                f"source_type: {reference.source_type}",
                f"issue_id: {reference.issue_id}",
                f"similarity: {reference.similarity:.6f}",
                f"rerank_score: {reference.rerank_score}",
                f"text_preview: {reference.text_preview}",
                "-" * 100,
            ]
        )

    return "\n".join(lines)