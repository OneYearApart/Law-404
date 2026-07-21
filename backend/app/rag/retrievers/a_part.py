from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import load_dotenv
from openai import OpenAI
from pgvector.psycopg2 import register_vector

PROJECT_ROOT = Path(__file__).resolve().parents[4]

load_dotenv(PROJECT_ROOT / "backend" / ".env")
load_dotenv(PROJECT_ROOT / ".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://edu:1234@localhost:5435/edudb",
)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

EMBEDDING_MODEL = os.getenv(
    "OPENAI_EMBEDDING_MODEL",
    "text-embedding-3-small",
)

DATASET_VERSION = os.getenv(
    "RAG_DATASET_VERSION",
    "law404-rag-v1",
)

CODE_VERSION = "routing-rerank-v10-final-service-evidence"


ALL_COLLECTIONS = [
    "legal_sources",
    "procedure_sources",
    "safety_guarantee_sources",
    "document_analysis_sources",
]


ROUTING_RULES: list[dict[str, Any]] = [
    {
        "route_id": "account_change",
        "keywords": [
            "계약 직전",
            "계좌가 바뀌",
            "계좌 변경",
            "계좌를 바꾸",
            "다른 계좌",
            "새 계좌",
        ],
        "collections": [
            "safety_guarantee_sources",
            "document_analysis_sources",
        ],
        "strong_keywords": [
            "계좌",
            "계좌 변경",
            "예금주",
            "확인",
            "계약상대방",
            "임대인",
            "대리인",
            "보류",
            "신분증",
            "소유자",
        ],
    },
    {
        "route_id": "special_clause_return",
        "keywords": [
            "계약금 반환",
            "반환 조건",
            "반환 사유",
            "반환 특약",
            "특약이나 계약금",
        ],
        "collections": [
            "document_analysis_sources",
            "safety_guarantee_sources",
            "legal_sources",
        ],
        "strong_keywords": [
            "특약",
            "계약금 반환",
            "반환 조건",
            "반환 사유",
            "반환 범위",
            "반환 기한",
            "해제",
            "서면",
        ],
    },
    {
        "route_id": "household_certificate",
        "keywords": [
            "전입세대확인서",
            "전입세대 확인서",
            "전입세대 열람",
            "전입세대열람",
        ],
        "collections": [
            "procedure_sources",
            "document_analysis_sources",
            "legal_sources",
        ],
        "strong_keywords": [
            "전입세대확인서",
            "세대주",
            "동거인",
            "전입일자",
            "계약 전",
            "잔금 전",
            "선순위",
            "기존 전입",
            "점유",
        ],
    },
    {
        "route_id": "deposit_transfer_mismatch",
        "keywords": [
            "계약서 보증금",
            "보증금이랑",
            "이체 내역",
            "이체내역",
            "금액이 다르",
            "보증금 금액",
            "입금내역",
        ],
        "collections": [
            "document_analysis_sources",
            "safety_guarantee_sources",
        ],
        "strong_keywords": [
            "보증금",
            "이체 내역",
            "이체내역",
            "입금내역",
            "금액",
            "불일치",
            "확인",
            "계약서",
        ],
    },
    {
        "route_id": "owner_proxy",
        "keywords": [
            "집주인 아들",
            "아들",
            "대신 계약",
            "대리",
            "대리인",
            "위임장",
            "대리권",
            "소유자",
            "공동명의",
            "공동소유",
        ],
        "collections": [
            "procedure_sources",
            "legal_sources",
            "safety_guarantee_sources",
            "document_analysis_sources",
        ],
        "strong_keywords": [
            "대리",
            "위임장",
            "대리권",
            "소유자",
            "공동명의",
            "공동소유자",
            "권한",
            "동의",
            "계약당사자",
        ],
    },
    {
        "route_id": "account_payment",
        "keywords": [
            "계좌",
            "송금",
            "계약금",
            "잔금",
            "예금주",
            "부동산 계좌",
            "중개사 계좌",
            "이체",
        ],
        "collections": [
            "safety_guarantee_sources",
            "document_analysis_sources",
            "legal_sources",
        ],
        "strong_keywords": [
            "계좌",
            "송금",
            "계약금",
            "잔금",
            "예금주",
            "이체",
            "지급계좌",
            "입금내역",
            "수령 권한",
            "보류",
        ],
    },
    {
        "route_id": "broker_explanation",
        "keywords": [
            "중개대상물",
            "확인설명서",
            "확인 설명서",
            "중개대상물 확인",
            "중개사 설명",
        ],
        "collections": [
            "document_analysis_sources",
            "legal_sources",
        ],
        "strong_keywords": [
            "중개대상물",
            "확인설명서",
            "확인ㆍ설명",
            "확인·설명",
            "공인중개사",
            "권리관계",
            "불일치",
        ],
    },
    {
        "route_id": "registry_risk",
        "keywords": [
            "근저당",
            "압류",
            "가압류",
            "가처분",
            "가등기",
            "경매",
            "신탁",
            "신탁등기",
            "선순위",
            "다가구",
            "다세대",
            "등기부",
            "등기부등본",
            "권리관계",
        ],
        "collections": [
            "legal_sources",
            "safety_guarantee_sources",
            "document_analysis_sources",
        ],
        "strong_keywords": [
            "근저당",
            "압류",
            "가압류",
            "가처분",
            "가등기",
            "경매",
            "신탁",
            "신탁등기",
            "수탁자",
            "신탁원부",
            "선순위",
            "다가구",
            "권리관계",
            "등기부등본",
        ],
    },
    {
        "route_id": "lease_report",
        "keywords": [
            "주택 임대차신고",
            "임대차신고",
            "임대차계약신고",
            "신고필증",
            "신고대상",
            "계약체결일",
        ],
        "collections": [
            "procedure_sources",
            "legal_sources",
            "document_analysis_sources",
        ],
        "strong_keywords": [
            "주택 임대차신고",
            "임대차신고",
            "임대차계약신고",
            "신고필증",
            "신고대상",
            "계약체결일",
            "부동산거래신고",
        ],
    },
    {
        "route_id": "protection_procedure",
        "keywords": [
            "전입신고",
            "확정일자",
            "대항력",
            "우선변제",
            "우선변제권",
            "전입세대확인서",
            "전입세대",
            "계약서 쓴 직후",
            "바로 해야",
            "절차",
        ],
        "collections": [
            "procedure_sources",
            "legal_sources",
            "safety_guarantee_sources",
        ],
        "strong_keywords": [
            "전입신고",
            "확정일자",
            "대항력",
            "우선변제권",
            "전입세대확인서",
            "절차",
            "계약 체결 후",
            "다음 날",
            "0시",
        ],
    },
    {
        "route_id": "document_mismatch",
        "keywords": [
            "계약서 주소",
            "등기부등본 주소",
            "주소가",
            "주소와",
            "조금 다른",
            "불일치",
            "다르면",
            "비교",
            "임대인 이름",
            "소유자랑",
        ],
        "collections": [
            "document_analysis_sources",
            "safety_guarantee_sources",
            "legal_sources",
        ],
        "strong_keywords": [
            "계약서",
            "등기부등본",
            "주소",
            "불일치",
            "비교",
            "소유자",
            "임대인",
            "확인",
            "공부상",
        ],
    },
    {
        "route_id": "guarantee",
        "keywords": [
            "전세보증금반환보증",
            "반환보증",
            "보증보험",
            "HUG",
            "허그",
            "가입",
        ],
        "collections": [
            "safety_guarantee_sources",
            "procedure_sources",
            "legal_sources",
        ],
        "strong_keywords": [
            "전세보증금반환보증",
            "반환보증",
            "보증",
            "보증보험",
            "가입",
            "HUG",
            "안심전세",
        ],
    },
    {
        "route_id": "owner_change",
        "keywords": [
            "집주인이 바뀌",
            "집주인 바뀌",
            "임대인이 바뀌",
            "소유자가 바뀌",
            "소유권 이전",
            "임대인 변경",
            "임대인 지위",
            "보증금은 어떻게",
        ],
        "collections": [
            "legal_sources",
            "safety_guarantee_sources",
        ],
        "strong_keywords": [
            "소유권 이전",
            "임대인 지위",
            "승계",
            "보증금반환채무",
            "양수인",
            "보증금",
        ],
    },
]


ISSUE_ROUTING_RULES: list[dict[str, Any]] = [
    {
        "issue_id": "01_owner_proxy",
        "keywords": [
            "집주인 아들",
            "대신 계약",
            "대리",
            "대리인",
            "위임장",
            "대리권",
            "공동명의",
            "공동소유",
            "소유자 한 명",
            "임대인 이름",
            "소유자랑",
        ],
        "negative_issue_ids": [
            "09_owner_change",
            "03_mortgage",
            "06_trust",
            "05_attachment_auction",
            "10_payment_special_clause",
        ],
    },
    {
        "issue_id": "03_mortgage",
        "keywords": [
            "근저당",
            "공동근저당",
            "채권최고액",
            "근저당권",
        ],
        "negative_issue_ids": [
            "06_trust",
            "05_attachment_auction",
            "04_multiunit_priority",
            "09_owner_change",
        ],
    },
    {
        "issue_id": "04_multiunit_priority",
        "keywords": [
            "다가구",
            "선순위 보증금",
            "선순위",
            "확정일자 부여현황",
            "보증금이 많",
            "보증금 합계",
        ],
        "negative_issue_ids": [
            "05_attachment_auction",
            "06_trust",
            "03_mortgage",
            "09_owner_change",
        ],
    },
    {
        "issue_id": "05_attachment_auction",
        "keywords": [
            "압류",
            "가압류",
            "가처분",
            "경매",
            "배당요구",
            "계약을 멈",
        ],
        "negative_issue_ids": [
            "06_trust",
            "03_mortgage",
            "04_multiunit_priority",
            "09_owner_change",
        ],
    },
    {
        "issue_id": "06_trust",
        "keywords": [
            "신탁",
            "신탁등기",
            "수탁자",
            "신탁원부",
            "임대 권한",
        ],
        "negative_issue_ids": [
            "03_mortgage",
            "05_attachment_auction",
            "04_multiunit_priority",
            "09_owner_change",
        ],
    },
    {
        "issue_id": "07_opposability_fixed_date",
        "keywords": [
            "전입신고",
            "대항력",
            "주민등록",
            "점유",
            "다음 날",
            "0시",
        ],
        "negative_issue_ids": [
            "09_owner_change",
            "03_mortgage",
            "06_trust",
        ],
    },
    {
        "issue_id": "08_priority_payment",
        "keywords": [
            "확정일자",
            "우선변제",
            "우선변제권",
            "임대차계약증서",
        ],
        "negative_issue_ids": [
            "07_opposability_fixed_date",
            "09_owner_change",
            "03_mortgage",
        ],
    },
    {
        "issue_id": "09_owner_change",
        "keywords": [
            "집주인이 바뀌",
            "임대인이 바뀌",
            "소유권 이전",
            "임대인 지위",
            "승계",
            "양수인",
        ],
        "negative_issue_ids": [
            "01_owner_proxy",
            "03_mortgage",
            "06_trust",
            "05_attachment_auction",
        ],
    },
    {
        "issue_id": "10_payment_special_clause",
        "keywords": [
            "계좌",
            "송금",
            "계약금",
            "잔금",
            "예금주",
            "이체",
            "특약",
            "계약금 반환",
        ],
        "negative_issue_ids": [
            "09_owner_change",
            "03_mortgage",
            "06_trust",
        ],
    },
]


def get_openai_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY가 설정되어 있지 않습니다.")

    return OpenAI(api_key=OPENAI_API_KEY)


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def embed_query(query: str) -> list[float]:
    query = normalize_text(query)

    if not query:
        raise ValueError("검색 질문이 비어 있습니다.")

    client = get_openai_client()

    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=[query],
    )

    return response.data[0].embedding


def to_pgvector_literal(embedding: list[float]) -> str:
    if not embedding:
        raise ValueError("embedding 값이 비어 있습니다.")

    return "[" + ",".join(str(float(value)) for value in embedding) + "]"


def contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def matched_keywords(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword in text]


def unique_extend(target: list[str], values: list[str]) -> None:
    for value in values:
        if value not in target:
            target.append(value)


def authority_anchor_document_ids(query: str) -> list[str]:
    """질문별로 기존 DB의 직접 근거 문서를 앵커로 반환한다."""
    normalized_query = normalize_text(query)

    # 계약금 반환 특약 질문은 공식 표준계약서와 HUG 안내를 조합해
    # 만든 출처 추적 서비스 카드와 해당 원문을 함께 올린다.
    if (
        contains_any(normalized_query, ["특약", "반환 특약"])
        and contains_any(
            normalized_query,
            ["계약금 반환", "반환 조건", "반환 사유", "계약금을 반환"],
        )
    ):
        return [
            "law404_special_clause_return_rule_c0001",
            "moj_standard_contract_2023_10_06_p2_c0003",
            "hug_during_contract_cautions_phtml_c0001",
        ]

    # 전입세대확인서 질문은 확인 범위와 계약 전·잔금 전 재확인 시점을
    # 정리한 출처 추적 서비스 카드와 정부24·표준계약서 원문을 올린다.
    if contains_any(
        normalized_query,
        ["전입세대확인서", "전입세대 확인서", "전입세대 열람", "전입세대열람"],
    ):
        return [
            "law404_household_certificate_timing_rule_c0001",
            "gov_household_certificate_phtml_c0005",
            "moj_standard_contract_2023_10_06_p2_c0003",
        ]

    # 신탁등기 질문은 신탁원부, 수탁자·위탁자, 임대 권한과
    # 수탁자 동의를 직접 설명하는 판례·공식 안내를 올린다.
    if contains_any(
        normalized_query,
        ["신탁등기", "신탁원부", "수탁자", "신탁"],
    ):
        return [
            "prec_206299_06_trust__part_001",
            "prec_231467_06_trust__part_001",
            "hug_fraud_cases_actions_phtml_c0001",
        ]

    # 확정일자·우선변제권 질문은 확정일자뿐 아니라 대항요건을
    # 함께 설명하는 법령과 판례를 올린다.
    if contains_any(
        normalized_query,
        ["확정일자", "우선변제권", "우선변제"],
    ):
        return [
            "law_001248_제3조의2__part_001",
            "prec_195162_08_priority_payment__part_001",
            "prec_191649_08_priority_payment__part_001",
        ]

    # 전입신고·대항력 질문은 주택 인도와 주민등록을 모두 갖춘
    # 다음 날 효력 발생 원칙을 직접 설명하는 근거를 올린다.
    if contains_any(
        normalized_query,
        ["전입신고", "대항력", "주민등록", "주택 인도"],
    ):
        return [
            "law_001248_제3조",
            "hug_after_contract_cautions_phtml_c0002",
            "prec_196635_07_opposability__part_001",
        ]

    # 다가구주택은 다른 세대의 선순위 보증금과 주택가액·권리관계를
    # 함께 설명하는 서로 다른 판례를 올린다.
    if contains_any(
        normalized_query,
        ["다가구", "선순위 보증금", "선순위 임차인", "보증금이 많"],
    ):
        return [
            "prec_160691_04_multiunit_priority__part_001",
            "prec_223315_02_broker_explanation__part_001",
            "prec_238189_02_broker_explanation__part_003",
        ]

    # 근저당 질문은 저당권 확인 의무, 보증금, 주택가액을 서로 다른
    # 공식 법령·판례로 조합한다.
    if contains_any(
        normalized_query,
        ["근저당", "근저당권", "채권최고액", "공동근저당"],
    ):
        return [
            "law_003673_제21조__part_001",
            "law_001248_제8조",
            "prec_173638_03_mortgage__part_002",
        ]

    # 압류·가압류 질문은 등기상 권리 제한과 말소·배당 영향을 직접
    # 설명하는 등기규칙·판례를 올린다.
    if contains_any(
        normalized_query,
        ["압류", "가압류", "가처분", "가등기", "권리 제한"],
    ):
        return [
            "law_005868_제147조",
            "prec_202714_08_priority_payment__part_003",
            "law_009290_제105조",
        ]

    # 계약서와 등기부 주소가 다른 질문은 계약서의 목적물 표시 기준과
    # 주소·호수 표기가 임대차 공시에 미치는 영향을 설명하는 근거를 올린다.
    if (
        contains_any(normalized_query, ["계약서 주소", "주소가", "주소와"])
        and contains_any(normalized_query, ["등기부등본", "등기부", "등기사항"])
        and contains_any(normalized_query, ["다른", "다르면", "차이", "불일치"])
    ):
        return [
            "moj_standard_contract_2023_10_06_p1_c0001",
            "prec_196703_01_owner_proxy__part_003",
        ]

    # 계약서 보증금과 이체 내역이 다른 질문은 계약서의 금액·지급일정과
    # 공식 지급 증빙 기준을 서로 다른 공식 원문으로 조합한다.
    if (
        contains_any(normalized_query, ["계약서", "보증금"])
        and contains_any(normalized_query, ["이체 내역", "이체내역", "송금 내역", "입금내역"])
        and contains_any(normalized_query, ["다르", "차액", "불일치", "합계"])
    ):
        return [
            "moj_standard_contract_2023_10_06_p1_c0002",
            "hug_guarantee_goods_phtml_c0001",
        ]

    # 계약 직전 계좌 변경은 계약 내용 일치 여부와 수령 권한을
    # 서로 다른 공식 원문으로 확인해야 한다.
    if contains_any(
        normalized_query,
        [
            "계약 직전",
            "계좌가 바뀌",
            "계좌 변경",
            "계좌를 바꾸",
            "변경된 계좌",
            "새 계좌",
        ],
    ):
        return [
            "law404_payment_recipient_authority_rule_c0001",
            "hug_during_contract_cautions_phtml_c0001",
            "moj_standard_contract_2023_10_06_p1_c0002",
            "law_001706_제471조",
            "law_001706_제472조",
        ]

    # 중개사·부동산 등 제3자 명의 계좌로 계약금을 보내라는 경우다.
    if (
        contains_any(
            normalized_query,
            ["부동산 계좌", "중개사 계좌", "제3자 계좌"],
        )
        or (
            contains_any(normalized_query, ["계약금", "잔금"])
            and contains_any(
                normalized_query,
                ["계좌", "송금", "보내", "예금주"],
            )
        )
    ):
        return [
            "law404_payment_recipient_authority_rule_c0001",
            "hug_during_contract_cautions_phtml_c0001",
            "moj_standard_contract_2023_10_06_p1_c0002",
            "law_001706_제471조",
            "law_001706_제472조",
        ]

    if contains_any(
        normalized_query,
        ["공동명의", "공동소유", "소유자 한 명", "집주인이 여러 명"],
    ):
        return [
            "moj_lease_protection_guide_p45_c0001",
            "law_001706_제264조",
            "law_001706_제265조",
        ]

    if (
        contains_any(
            normalized_query,
            ["등기부등본 소유자", "등기부 소유자", "소유자랑", "소유자와"],
        )
        and contains_any(
            normalized_query,
            ["계약서", "임대인", "이름이 다", "다른데", "불일치"],
        )
    ):
        return [
            "prec_82972_01_owner_proxy__part_001",
            "moj_lease_protection_guide_p44_c0001",
        ]

    if contains_any(
        normalized_query,
        ["집주인 아들", "대신 계약", "대리인", "위임장", "대리권"],
    ):
        return [
            "moj_lease_protection_guide_p44_c0001",
            "law_001706_제130조",
            "law_001706_제131조",
            "law_001706_제134조",
            "law_001706_제135조",
        ]

    return []


def route_query(query: str) -> dict[str, Any]:
    normalized_query = normalize_text(query)

    matched_route_ids: list[str] = []
    routed_collections: list[str] = []
    strong_keywords: list[str] = []

    for rule in ROUTING_RULES:
        if contains_any(normalized_query, rule["keywords"]):
            matched_route_ids.append(rule["route_id"])
            unique_extend(routed_collections, rule["collections"])
            unique_extend(strong_keywords, rule["strong_keywords"])

    target_issue_ids: list[str] = []
    negative_issue_ids: list[str] = []

    for rule in ISSUE_ROUTING_RULES:
        if contains_any(normalized_query, rule["keywords"]):
            unique_extend(target_issue_ids, [rule["issue_id"]])
            unique_extend(negative_issue_ids, rule["negative_issue_ids"])

    if not routed_collections:
        routed_collections = ALL_COLLECTIONS.copy()

    if "account_change" in matched_route_ids:
        routed_collections = [
            "safety_guarantee_sources",
            "document_analysis_sources",
            "legal_sources",
        ]

    if "deposit_transfer_mismatch" in matched_route_ids:
        routed_collections = [
            "document_analysis_sources",
            "safety_guarantee_sources",
            "legal_sources",
        ]

    return {
        "query": normalized_query,
        "matched_route_ids": matched_route_ids,
        "anchor_document_ids": authority_anchor_document_ids(normalized_query),
        "collections": routed_collections,
        "strong_keywords": strong_keywords,
        "target_issue_ids": target_issue_ids,
        "negative_issue_ids": negative_issue_ids,
    }


def build_collection_priority(collections: list[str]) -> dict[str, int]:
    return {
        collection: index
        for index, collection in enumerate(collections)
    }


def fetch_vector_candidates(
    query_vector: str,
    top_k: int,
    collections: list[str] | None,
    min_similarity: float | None = None,
) -> list[dict[str, Any]]:
    where_clauses = ["dataset_version = %s"]
    params: list[Any] = [DATASET_VERSION]

    if collections:
        placeholders = ", ".join(["%s"] * len(collections))
        where_clauses.append(f"collection IN ({placeholders})")
        params.extend(collections)

    where_sql = "WHERE " + " AND ".join(where_clauses)

    sql = f"""
    SELECT
        collection,
        document_id,
        source_id,
        source_type,
        title,
        text,
        metadata,
        1 - (embedding <=> %s::vector) AS similarity
    FROM a_part_rag_documents
    {where_sql}
    ORDER BY embedding <=> %s::vector
    LIMIT %s;
    """

    final_params = [query_vector] + params + [query_vector, top_k]

    rows: list[tuple[Any, ...]]

    with psycopg2.connect(DATABASE_URL) as conn:
        register_vector(conn)

        with conn.cursor() as cur:
            cur.execute(sql, final_params)
            rows = cur.fetchall()

    results: list[dict[str, Any]] = []

    for row in rows:
        result = {
            "collection": row[0],
            "document_id": row[1],
            "source_id": row[2],
            "source_type": row[3],
            "title": row[4],
            "text": row[5],
            "metadata": row[6] if isinstance(row[6], dict) else {},
            "similarity": float(row[7]),
        }

        if min_similarity is None or result["similarity"] >= min_similarity:
            results.append(result)

    return results


def fetch_anchor_candidates(
    query_vector: str,
    document_ids: list[str],
) -> list[dict[str, Any]]:
    """벡터 순위와 무관하게 공식 앵커 문서를 후보에 보충한다."""
    if not document_ids:
        return []

    sql = """
    SELECT
        collection,
        document_id,
        source_id,
        source_type,
        title,
        text,
        metadata,
        1 - (embedding <=> %s::vector) AS similarity
    FROM a_part_rag_documents
    WHERE dataset_version = %s
      AND document_id = ANY(%s);
    """

    with psycopg2.connect(DATABASE_URL) as conn:
        register_vector(conn)

        with conn.cursor() as cur:
            cur.execute(
                sql,
                (query_vector, DATASET_VERSION, document_ids),
            )
            rows = cur.fetchall()

    return [
        {
            "collection": row[0],
            "document_id": row[1],
            "source_id": row[2],
            "source_type": row[3],
            "title": row[4],
            "text": row[5],
            "metadata": row[6] if isinstance(row[6], dict) else {},
            "similarity": float(row[7]),
            "anchor_match": True,
        }
        for row in rows
    ]


def merge_candidates(
    vector_candidates: list[dict[str, Any]],
    anchor_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    positions: dict[tuple[str, str], int] = {}

    for result in [*vector_candidates, *anchor_candidates]:
        key = (
            normalize_text(result.get("collection")),
            normalize_text(result.get("document_id")),
        )

        if key in positions:
            existing = merged[positions[key]]
            if result.get("anchor_match"):
                existing["anchor_match"] = True
            continue

        positions[key] = len(merged)
        merged.append(result)

    return merged


def is_summary_chunk(metadata: dict[str, Any], text: str) -> bool:
    chunk_index = metadata.get("chunk_index")

    if chunk_index == 1:
        return True

    return text.startswith("[쟁점]")


def score_result(
    result: dict[str, Any],
    route_info: dict[str, Any],
    collection_priority: dict[str, int],
) -> float:
    score = float(result.get("similarity") or 0.0)

    collection = result.get("collection")
    title = normalize_text(result.get("title"))
    text = normalize_text(result.get("text"))
    metadata = result.get("metadata") or {}

    metadata_issue_id = normalize_text(metadata.get("issue_id"))
    metadata_primary_flow = normalize_text(metadata.get("primary_flow"))
    metadata_source_title = normalize_text(metadata.get("source_title"))
    document_id = normalize_text(result.get("document_id"))

    searchable = " ".join(
        [
            title,
            text,
            metadata_issue_id,
            metadata_primary_flow,
            metadata_source_title,
            document_id,
        ]
    )

    matched_route_ids = route_info.get("matched_route_ids", [])
    anchor_document_ids = set(route_info.get("anchor_document_ids", []))
    target_issue_ids = route_info.get("target_issue_ids", [])
    negative_issue_ids = route_info.get("negative_issue_ids", [])

    if collection in collection_priority:
        priority_index = collection_priority[collection]
        score += max(0.0, 0.08 - (priority_index * 0.02))

    if document_id in anchor_document_ids or result.get("anchor_match"):
        score += 1.10

    keyword_matches = matched_keywords(
        searchable,
        route_info.get("strong_keywords", []),
    )

    score += min(len(keyword_matches) * 0.025, 0.15)

    if metadata_issue_id in target_issue_ids:
        issue_bonus = 0.36

        if metadata_issue_id == "03_mortgage":
            issue_bonus = 0.62

        if metadata_issue_id == "04_multiunit_priority":
            issue_bonus = 0.72

        if metadata_issue_id == "05_attachment_auction":
            issue_bonus = 0.72

        if metadata_issue_id == "06_trust":
            issue_bonus = 0.68

        if metadata_issue_id == "07_opposability_fixed_date":
            issue_bonus = 0.62

        if metadata_issue_id == "08_priority_payment":
            issue_bonus = 0.66

        if metadata_issue_id == "10_payment_special_clause" and "account_change" in matched_route_ids:
            issue_bonus = 0.08

        score += issue_bonus

        if is_summary_chunk(metadata, text):
            score += 0.14
        else:
            score -= 0.10

    if metadata_issue_id in negative_issue_ids:
        score -= 0.24

    if target_issue_ids and not metadata_issue_id:
        if collection == "safety_guarantee_sources":
            score += 0.03
        else:
            score -= 0.03

    if "account_change" in matched_route_ids:
        if collection == "safety_guarantee_sources":
            score += 0.45

        if collection == "document_analysis_sources":
            score += 0.28

        if collection == "legal_sources":
            score -= 0.42

        if contains_any(searchable, ["계약상대방", "임대인", "대리인", "소유자", "신분증", "계약 내용", "특약사항"]):
            score += 0.20

        if contains_any(searchable, ["계좌", "예금주", "지급계좌", "입금내역", "이체내역"]):
            score += 0.16

    if "special_clause_return" in matched_route_ids:
        if collection == "document_analysis_sources":
            score += 0.50
        if collection == "safety_guarantee_sources":
            score += 0.20
        if collection == "legal_sources":
            score += 0.08

        document_id = normalize_text(result.get("document_id"))
        if document_id == "law404_special_clause_return_rule_c0001":
            score += 1.25
        if document_id == "moj_standard_contract_2023_10_06_p2_c0003":
            score += 0.85
        if document_id == "hug_during_contract_cautions_phtml_c0001":
            score += 0.55

        if contains_any(
            searchable,
            [
                "특약",
                "계약금 반환",
                "반환 조건",
                "반환 사유",
                "반환 범위",
                "반환 기한",
                "포기하지 않고",
                "임대차계약을 해제",
            ],
        ):
            score += 0.32

    if "household_certificate" in matched_route_ids:
        if collection == "procedure_sources":
            score += 0.55
        if collection == "document_analysis_sources":
            score += 0.18
        if collection == "legal_sources":
            score -= 0.16

        document_id = normalize_text(result.get("document_id"))
        if document_id == "law404_household_certificate_timing_rule_c0001":
            score += 1.25
        if document_id == "gov_household_certificate_phtml_c0005":
            score += 0.90
        if document_id == "moj_standard_contract_2023_10_06_p2_c0003":
            score += 0.65

        if contains_any(
            searchable,
            [
                "전입세대확인서",
                "세대주",
                "동거인",
                "전입일자",
                "계약 전",
                "잔금 전",
                "선순위",
                "기존 전입",
                "점유",
            ],
        ):
            score += 0.32

    if "deposit_transfer_mismatch" in matched_route_ids:
        if collection == "document_analysis_sources":
            score += 0.52

        if collection == "safety_guarantee_sources":
            score += 0.28

        if collection == "legal_sources":
            score -= 0.45

        document_id = normalize_text(result.get("document_id"))
        if document_id == "moj_standard_contract_2023_10_06_p1_c0002":
            score += 1.10
        if document_id == "hug_guarantee_goods_phtml_c0001":
            score += 1.05

        if contains_any(searchable, ["보증금", "계약금", "중도금", "잔금", "이체 내역", "이체내역", "입금내역", "영수증", "금액", "계약서"]):
            score += 0.28

    if "document_mismatch" in matched_route_ids:
        if collection == "document_analysis_sources":
            score += 0.24

        if contains_any(route_info["query"], ["주소", "계약서 주소", "등기부등본 주소"]):
            if collection == "document_analysis_sources":
                score += 0.34

            document_id = normalize_text(result.get("document_id"))
            if document_id == "moj_standard_contract_2023_10_06_p1_c0001":
                score += 1.15
            if document_id == "prec_196703_01_owner_proxy__part_003":
                score += 1.10

            if contains_any(searchable, ["주소", "도로명주소", "지번", "동", "층", "호", "임차할부분", "소재지", "등기부등본", "계약서", "주민등록"]):
                score += 0.20

            if collection == "safety_guarantee_sources":
                score -= 0.18

    if "lease_report" in matched_route_ids:
        if collection == "procedure_sources":
            score += 0.32

        if collection == "legal_sources":
            score += 0.08

        if contains_any(searchable, ["임대차신고", "임대차계약신고", "주택 임대차신고", "신고필증", "계약체결일", "신고대상"]):
            score += 0.42
        else:
            score -= 0.36

    if "protection_procedure" in matched_route_ids:
        if contains_any(route_info["query"], ["전입신고", "대항력"]):
            if metadata_issue_id == "07_opposability_fixed_date":
                score += 0.34

            if document_id in {
                "law_001248_제3조",
                "hug_after_contract_cautions_phtml_c0002",
                "prec_196635_07_opposability__part_001",
            }:
                score += 0.48

            if contains_any(
                searchable,
                [
                    "주택의 인도",
                    "전입신고",
                    "주민등록",
                    "다음 날",
                    "익일",
                    "대항력",
                ],
            ):
                score += 0.24

            if metadata_issue_id == "08_priority_payment":
                score -= 0.12

        if contains_any(route_info["query"], ["확정일자", "우선변제", "우선변제권"]):
            if metadata_issue_id == "08_priority_payment":
                score += 0.38

            if document_id in {
                "law_001248_제3조의2__part_001",
                "prec_195162_08_priority_payment__part_001",
                "prec_191649_08_priority_payment__part_001",
            }:
                score += 0.48

            if contains_any(
                searchable,
                [
                    "확정일자",
                    "우선변제권",
                    "우선변제",
                    "대항요건",
                    "주택의 인도",
                    "주민등록",
                    "전입신고",
                ],
            ):
                score += 0.24

            if metadata_issue_id == "07_opposability_fixed_date":
                score -= 0.08

    if "registry_risk" in matched_route_ids:
        if contains_any(route_info["query"], ["신탁등기", "신탁원부", "수탁자", "신탁"]):
            if metadata_issue_id == "06_trust":
                score += 0.44

            if document_id in {
                "prec_206299_06_trust__part_001",
                "prec_231467_06_trust__part_001",
                "hug_fraud_cases_actions_phtml_c0001",
            }:
                score += 0.50

            if contains_any(
                searchable,
                [
                    "신탁등기",
                    "신탁원부",
                    "수탁자",
                    "위탁자",
                    "임대권한",
                    "임대 권한",
                    "동의",
                    "사전 승낙",
                ],
            ):
                score += 0.22

            if metadata_issue_id in {
                "03_mortgage",
                "04_multiunit_priority",
                "05_attachment_auction",
            }:
                score -= 0.20

        if contains_any(route_info["query"], ["근저당", "채권최고액", "공동근저당"]):
            if metadata_issue_id == "03_mortgage":
                score += 0.34

            if document_id in {
                "law_003673_제21조__part_001",
                "law_001248_제8조",
                "prec_173638_03_mortgage__part_002",
            }:
                score += 0.46

            if metadata_issue_id == "06_trust":
                score -= 0.24

        if contains_any(route_info["query"], ["다가구", "선순위 보증금", "선순위"]):
            if metadata_issue_id == "04_multiunit_priority":
                score += 0.38

            if document_id in {
                "prec_160691_04_multiunit_priority__part_001",
                "prec_223315_02_broker_explanation__part_001",
                "prec_238189_02_broker_explanation__part_003",
            }:
                score += 0.48

            if metadata_issue_id == "05_attachment_auction":
                score -= 0.22

        if contains_any(route_info["query"], ["압류", "가압류", "가처분", "경매"]):
            if metadata_issue_id == "05_attachment_auction":
                score += 0.42

            if document_id in {
                "law_005868_제147조",
                "prec_202714_08_priority_payment__part_003",
                "law_009290_제105조",
            }:
                score += 0.46

            if collection == "legal_sources" and metadata_issue_id == "05_attachment_auction":
                score += 0.20

            if collection == "safety_guarantee_sources" and not metadata_issue_id:
                score -= 0.06

            if metadata_issue_id in ["06_trust", "04_multiunit_priority"]:
                score -= 0.12

    if "owner_proxy" in matched_route_ids:
        if metadata_issue_id == "01_owner_proxy":
            score += 0.12

        if metadata_issue_id == "09_owner_change":
            score -= 0.16

        if collection == "procedure_sources":
            score += 0.18

        if contains_any(route_info["query"], ["공동명의", "공동소유", "소유자 한 명"]):
            if document_id == "moj_lease_protection_guide_p45_c0001":
                score += 0.35
            if document_id in {"law_001706_제264조", "law_001706_제265조"}:
                score += 0.25

        elif contains_any(
            route_info["query"],
            ["등기부등본 소유자", "등기부 소유자", "소유자랑", "소유자와"],
        ):
            if document_id == "prec_82972_01_owner_proxy__part_001":
                score += 0.35
            if document_id == "moj_lease_protection_guide_p44_c0001":
                score += 0.25

        else:
            if document_id == "moj_lease_protection_guide_p44_c0001":
                score += 0.35
            if document_id in {
                "law_001706_제130조",
                "law_001706_제131조",
                "law_001706_제134조",
                "law_001706_제135조",
            }:
                score += 0.25

    if "owner_change" in matched_route_ids and metadata_issue_id == "09_owner_change":
        score += 0.16

    if "broker_explanation" in matched_route_ids and metadata_issue_id == "02_broker_explanation":
        score += 0.10

    if "account_payment" in matched_route_ids:
        if "special_clause_return" in matched_route_ids:
            if metadata_issue_id == "10_payment_special_clause":
                score -= 0.18
            if document_id in {
                "law404_payment_recipient_authority_rule_c0001",
                "law_001706_제471조",
                "law_001706_제472조",
            }:
                score -= 0.45

        if document_id == "law404_payment_recipient_authority_rule_c0001":
            score += 0.78
        if document_id == "hug_during_contract_cautions_phtml_c0001":
            score += 0.40
        if document_id == "moj_standard_contract_2023_10_06_p1_c0002":
            score += 0.34
        if document_id in {
            "law_001706_제471조",
            "law_001706_제472조",
        }:
            score += 0.38

        # 기존 10번 쟁점 판례는 계좌라는 단어가 있어도 실제 질문의
        # 수령 권한을 직접 설명하지 않는 경우가 많으므로 우선하지 않는다.
        if metadata_issue_id == "10_payment_special_clause":
            score -= 0.06

    if "guarantee" in matched_route_ids and collection == "safety_guarantee_sources":
        score += 0.10

    return score


def deduplicate_results(
    scored_results: list[dict[str, Any]],
    top_k: int,
    max_per_source: int = 2,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_document_ids: set[str] = set()
    source_counts: dict[str, int] = {}

    for result in scored_results:
        metadata = result.get("metadata") or {}
        document_key = (
            metadata.get("parent_document_id")
            or result.get("document_id")
            or ""
        )
        source_id = str(result.get("source_id") or "")

        if document_key and document_key in seen_document_ids:
            continue

        if source_id and source_counts.get(source_id, 0) >= max_per_source:
            continue

        selected.append(result)

        if document_key:
            seen_document_ids.add(document_key)

        if source_id:
            source_counts[source_id] = source_counts.get(source_id, 0) + 1

        if len(selected) >= top_k:
            break

    if len(selected) >= top_k:
        return selected

    for result in scored_results:
        if result in selected:
            continue

        selected.append(result)

        if len(selected) >= top_k:
            break

    return selected


def search_documents(
    query: str,
    top_k: int = 8,
    collections: list[str] | None = None,
    min_similarity: float | None = None,
    candidate_k: int = 80,
    use_routing: bool = True,
) -> list[dict[str, Any]]:
    if top_k <= 0:
        raise ValueError("top_k는 1 이상이어야 합니다.")

    if candidate_k < top_k:
        candidate_k = top_k

    route_info = route_query(query)

    if collections is None and use_routing:
        search_collections = route_info["collections"]
    else:
        search_collections = collections

    if search_collections:
        collection_priority = build_collection_priority(search_collections)
    else:
        collection_priority = build_collection_priority(ALL_COLLECTIONS)

    query_embedding = embed_query(query)
    query_vector = to_pgvector_literal(query_embedding)

    vector_candidates = fetch_vector_candidates(
        query_vector=query_vector,
        top_k=candidate_k,
        collections=search_collections,
        min_similarity=min_similarity,
    )
    anchor_candidates = fetch_anchor_candidates(
        query_vector=query_vector,
        document_ids=route_info.get("anchor_document_ids", []),
    )
    candidates = merge_candidates(
        vector_candidates=vector_candidates,
        anchor_candidates=anchor_candidates,
    )

    scored_results: list[dict[str, Any]] = []

    for result in candidates:
        rerank_score = score_result(
            result=result,
            route_info=route_info,
            collection_priority=collection_priority,
        )

        result["rerank_score"] = round(rerank_score, 6)
        result["code_version"] = CODE_VERSION
        result["matched_route_ids"] = route_info["matched_route_ids"]
        result["routed_collections"] = route_info["collections"]
        result["target_issue_ids"] = route_info["target_issue_ids"]
        result["negative_issue_ids"] = route_info["negative_issue_ids"]

        scored_results.append(result)

    scored_results.sort(
        key=lambda item: (
            float(item.get("rerank_score") or 0.0),
            float(item.get("similarity") or 0.0),
        ),
        reverse=True,
    )

    return deduplicate_results(
        scored_results=scored_results,
        top_k=top_k,
        max_per_source=2,
    )


def print_search_results(results: list[dict[str, Any]]) -> None:
    for index, result in enumerate(results, start=1):
        text = normalize_text(result.get("text"))
        preview = text[:300] + "..." if len(text) > 300 else text
        metadata = result.get("metadata") or {}

        print("=" * 100)
        print("순위:", index)
        print("collection:", result.get("collection"))
        print("document_id:", result.get("document_id"))
        print("source_id:", result.get("source_id"))
        print("source_type:", result.get("source_type"))
        print("title:", result.get("title"))
        print("issue_id:", metadata.get("issue_id"))
        print("similarity:", round(float(result.get("similarity") or 0.0), 6))
        print("rerank_score:", result.get("rerank_score"))
        print("matched_route_ids:", result.get("matched_route_ids"))
        print("target_issue_ids:", result.get("target_issue_ids"))
        print("routed_collections:", result.get("routed_collections"))
        print("text_preview:", preview)


if __name__ == "__main__":
    test_query = "계약 직전에 계좌가 바뀌었다고 하는데 어떻게 확인해야 하나요?"

    test_results = search_documents(
        query=test_query,
        top_k=8,
        collections=None,
        min_similarity=None,
        candidate_k=80,
        use_routing=True,
    )

    print("질문:", test_query)
    print("코드 버전:", CODE_VERSION)
    print_search_results(test_results)