from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[3]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


import psycopg2

import backend.app.rag.retrievers.a_part as retriever_module
from backend.app.rag.retrievers.a_part import search_documents

RESULT_DIR = PROJECT_ROOT / "backend" / "tests" / "a_part" / "results"
JSON_PATH = RESULT_DIR / "a_part_evidence_gap_analysis_v2.json"
CSV_PATH = RESULT_DIR / "a_part_evidence_gap_summary_v2.csv"


DATABASE_URL = getattr(
    retriever_module,
    "DATABASE_URL",
    os.getenv(
        "DATABASE_URL",
        "postgresql://edu:1234@localhost:5433/edudb",
    ),
)

DATASET_VERSION = getattr(
    retriever_module,
    "DATASET_VERSION",
    os.getenv("RAG_DATASET_VERSION", "law404-rag-v1"),
)


KeywordGroup = tuple[str, ...]


@dataclass(frozen=True)
class GapCase:
    question_id: str
    question: str
    topic: str
    required_groups: tuple[KeywordGroup, ...]
    broad_keywords: tuple[str, ...]
    weak_keywords: tuple[str, ...] = ()
    allow_composite: bool = False


GAP_CASES: tuple[GapCase, ...] = (
    GapCase(
        "q01_owner_proxy",
        "집주인 아들이 대신 계약하러 왔는데 위임장 없이 계약해도 되나요?",
        "대리 계약·위임 범위·수령 권한",
        (
            ("위임장", "대리권", "무권대리", "표현대리"),
            ("임대차", "임대인", "소유자", "계약"),
        ),
        ("위임장", "대리권", "무권대리", "표현대리", "대리인", "위임"),
        ("대리인", "위임"),
    ),
    GapCase(
        "q02_co_owner",
        "공동명의 집인데 소유자 한 명만 나와서 계약해도 되나요?",
        "공동소유자 동의·대리 권한",
        (
            ("공동소유", "공동명의", "공유자"),
            ("동의", "대리권", "위임", "처분"),
        ),
        ("공동소유", "공동명의", "공유자", "공유물", "동의", "위임"),
        ("공동소유", "공유자"),
    ),
    GapCase(
        "q03_owner_lessor_mismatch",
        "등기부등본 소유자랑 계약서 임대인 이름이 다른데 괜찮나요?",
        "소유자·임대인 불일치와 임대 권한",
        (
            ("소유자", "소유권"),
            ("임대인", "임대차"),
            ("대리권", "위임", "임대 권한", "계약 권한"),
        ),
        ("소유자", "임대인", "임대 권한", "계약 권한", "대리권", "위임"),
        ("소유자", "임대인"),
    ),
    GapCase(
        "q04_broker_account_payment",
        "부동산 계좌로 계약금을 보내라고 하는데 괜찮나요?",
        "제3자 계좌·계약금 수령 권한",
        (
            (
                "주택 소유자 본인이 맞는지 확인",
                "정당한 대리권이 있는지 확인",
                "영수증소지자에 대한 변제",
                "변제받을 권한없는 자",
            ),
            ("계약금", "지불하고 영수함", "영수자"),
            (
                "권한없음을 알았거나 알 수 있었을 경우",
                "채권자가 이익을 받은 한도",
                "변제를 받을 권한",
            ),
        ),
        (
            "주택 소유자 본인",
            "정당한 대리권",
            "계약금",
            "영수자",
            "변제받을 권한없는 자",
            "영수증소지자",
        ),
        ("계약금", "영수자", "대리권", "변제"),
        True,
    ),
    GapCase(
        "q05_account_change_before_contract",
        "계약 직전에 계좌가 바뀌었다고 하는데 어떻게 확인해야 하나요?",
        "계약 직전 계좌 변경 확인",
        (
            (
                "사전에 협의된 내용과 일치하는지 확인",
                "계약 내용 확인",
            ),
            (
                "주택 소유자 본인이 맞는지 확인",
                "정당한 대리권이 있는지 확인",
                "변제받을 권한없는 자",
            ),
            ("계약금", "지불하고 영수함", "영수자"),
        ),
        (
            "사전에 협의된 내용",
            "계약 내용 확인",
            "주택 소유자 본인",
            "정당한 대리권",
            "계약금",
            "영수자",
            "변제받을 권한없는 자",
        ),
        ("계약 내용", "계약금", "영수자", "대리권"),
        True,
    ),
    GapCase(
        "q07_mortgage",
        "등기부등본에 근저당이 있는데 전세계약해도 되나요?",
        "근저당·채권최고액·보증금·주택가액",
        (
            ("근저당", "저당권", "채권최고액"),
            ("보증금", "임차보증금", "전세보증금"),
            ("주택가액", "주택 가격", "주택가격", "시세", "감정가"),
        ),
        ("근저당", "저당권", "채권최고액", "임차보증금", "주택가액", "시세"),
        ("근저당", "채권최고액"),
        True,
    ),
    GapCase(
        "q08_multiunit_priority",
        "다가구주택인데 선순위 보증금이 많으면 위험한가요?",
        "다가구 선순위 보증금·주택가액",
        (
            ("다가구", "다세대"),
            ("선순위 보증금", "선순위 임차인", "선순위 임차보증금"),
            ("주택가액", "주택 가격", "주택가격", "시세", "감정가"),
        ),
        ("다가구", "선순위 보증금", "선순위 임차인", "선순위 임차보증금", "주택가액"),
        ("다가구", "선순위"),
        True,
    ),
    GapCase(
        "q09_registry_restriction_warning",
        "등기부등본에 압류, 가압류 같은 권리 제한이 있으면 계약 전에 어떻게 확인해야 하나요?",
        "등기부 압류·가압류 위험과 말소 확인",
        (
            ("압류", "가압류", "가처분", "가등기"),
            ("등기부", "부동산", "주택", "임대차"),
            ("말소", "해소", "권리관계", "선순위", "보증금"),
        ),
        ("압류", "가압류", "가처분", "가등기", "말소", "등기부"),
        ("압류", "가압류", "가처분"),
    ),
    GapCase(
        "q10_trust",
        "신탁등기가 있는 집인데 임대인이랑 바로 계약해도 되나요?",
        "신탁등기·신탁원부·수탁자 임대 권한",
        (
            ("신탁등기", "신탁원부", "신탁"),
            ("수탁자", "위탁자"),
            ("임대 권한", "임대권한", "동의", "계약 권한"),
        ),
        ("신탁등기", "신탁원부", "수탁자", "위탁자", "임대 권한", "동의"),
        ("신탁", "수탁자"),
    ),
    GapCase(
        "q11_opposability_move_in",
        "전입신고를 하면 대항력이 언제 생기나요?",
        "주택 인도·주민등록·다음 날 대항력",
        (
            ("주택의 인도", "주택 인도", "인도"),
            ("주민등록", "전입신고"),
            ("다음 날", "익일"),
            ("대항력",),
        ),
        ("주택의 인도", "주민등록", "전입신고", "다음 날", "대항력"),
        ("전입신고", "대항력"),
    ),
    GapCase(
        "q12_fixed_date_priority",
        "확정일자를 받으면 우선변제권이 생기나요?",
        "확정일자·대항요건·우선변제권",
        (
            ("확정일자",),
            ("우선변제권", "우선변제"),
            ("대항요건", "주택 인도", "주민등록", "전입신고"),
        ),
        ("확정일자", "우선변제권", "우선변제", "대항요건", "전입신고"),
        ("확정일자", "우선변제권"),
    ),
    GapCase(
        "q14_special_clause_deposit_return",
        "계약서 특약이나 계약금 반환 조건은 어떻게 확인해야 하나요?",
        "특약·계약금 반환 조건",
        (
            ("특약",),
            ("계약금", "계약보증금"),
            ("반환", "해제", "해약"),
            ("조건", "기한", "문구", "서면"),
            ("임대차", "임대인", "임차인", "주택"),
        ),
        ("특약", "계약금 반환", "계약금", "해제", "반환 조건", "서면"),
        ("특약", "계약금"),
    ),
    GapCase(
        "q17_household_certificate",
        "전입세대확인서는 언제 확인해야 하나요?",
        "전입세대확인서·계약 전·잔금 전·선순위",
        (
            ("전입세대확인서", "전입세대 열람", "전입세대열람"),
            ("계약 전", "계약체결 전"),
            ("잔금 전", "잔금 지급 전"),
            ("선순위", "기존 전입", "점유"),
        ),
        ("전입세대확인서", "전입세대 열람", "전입세대열람", "계약 전", "잔금 전", "선순위"),
        ("전입세대", "선순위"),
    ),
    GapCase(
        "q18_address_mismatch",
        "계약서 주소와 등기부등본 주소가 조금 다른데 어떻게 봐야 하나요?",
        "계약서·등기부 주소 불일치",
        (
            ("계약서",),
            ("등기부등본", "등기부"),
            ("주소", "소재지", "목적물"),
            ("지번", "도로명", "동호수", "동·호수", "건물명"),
            ("불일치", "다른", "차이", "오류", "정정", "대조", "일치"),
        ),
        ("계약서 주소", "등기부등본 주소", "소재지", "목적물", "지번", "도로명", "동호수"),
        ("주소", "소재지", "목적물"),
    ),
    GapCase(
        "q19_deposit_transfer_mismatch",
        "계약서 보증금이랑 이체 내역 금액이 다르면 어떻게 해야 하나요?",
        "계약서 보증금·이체 내역 불일치",
        (
            ("계약서",),
            ("보증금", "임차보증금", "전세보증금"),
            ("이체 내역", "이체내역", "송금 내역", "지급 내역"),
            ("차액", "불일치", "영수증", "수령 확인", "정산"),
        ),
        ("계약서", "보증금", "이체 내역", "송금 내역", "차액", "영수증", "정산"),
        ("보증금", "이체", "영수증"),
    ),
)


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).lower()


def _substantive_body(result: dict[str, Any]) -> str:
    raw_text = _normalize_text(result.get("text"))
    source_type = _normalize_text(result.get("source_type"))

    if not raw_text:
        return ""

    # 법령 카드의 [활용]·[태그]는 검색용 메타 설명이므로
    # 실제 조문인 [본문] 이후만 직접 근거 판정에 사용한다.
    if source_type == "law" and "[본문]" in raw_text:
        return raw_text.split("[본문]", 1)[1].strip()

    # 판례 카드의 [쟁점]·[활용]·[태그]가 아니라
    # 실제 판시사항·판결요지 부분을 직접 근거로 사용한다.
    if source_type == "precedent":
        if "[판시사항]" in raw_text:
            return raw_text.split("[판시사항]", 1)[1].strip()
        if "[판결요지]" in raw_text:
            return raw_text.split("[판결요지]", 1)[1].strip()

    return raw_text


def _candidate_topic_text(result: dict[str, Any]) -> str:
    # 후보를 찾거나 화면에 설명할 때만 제목과 metadata를 참고한다.
    # 직접 근거 판정에는 사용하지 않는다.
    metadata = result.get("metadata")
    metadata_text = (
        json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        if isinstance(metadata, dict)
        else str(metadata or "")
    )

    return _normalize_text(
        " ".join(
            [
                str(result.get("title") or ""),
                str(result.get("text") or ""),
                metadata_text,
            ]
        )
    )

def _matched_groups(
    text: str,
    groups: tuple[KeywordGroup, ...],
) -> list[list[str]]:
    return [
        [
            keyword
            for keyword in group
            if keyword.lower() in text
        ]
        for group in groups
    ]


def _all_groups_matched(matched_groups: list[list[str]]) -> bool:
    return bool(matched_groups) and all(matched_groups)


def _matched_group_count(matched_groups: list[list[str]]) -> int:
    return sum(1 for group in matched_groups if group)


def _weak_hits(text: str, keywords: Iterable[str]) -> list[str]:
    return [
        keyword
        for keyword in keywords
        if keyword.lower() in text
    ]


def _result_summary(
    result: dict[str, Any],
    rank: int | None = None,
) -> dict[str, Any]:
    text = _normalize_text(result.get("text"))
    preview = text[:500] + ("..." if len(text) > 500 else "")
    metadata = result.get("metadata")
    issue_id = (
        metadata.get("issue_id")
        if isinstance(metadata, dict)
        else None
    )

    return {
        "rank": rank,
        "collection": result.get("collection"),
        "document_id": result.get("document_id"),
        "source_id": result.get("source_id"),
        "source_type": result.get("source_type"),
        "title": result.get("title"),
        "issue_id": issue_id,
        "similarity": round(
            float(result.get("similarity") or 0.0),
            6,
        ),
        "rerank_score": result.get("rerank_score"),
        "text_preview": preview,
    }


def _semantic_search(case: GapCase) -> list[dict[str, Any]]:
    return search_documents(
        query=case.question,
        top_k=30,
        collections=None,
        min_similarity=0.20,
        candidate_k=150,
    )


def _db_lexical_scan(
    case: GapCase,
    limit: int = 300,
) -> list[dict[str, Any]]:
    patterns = [f"%{keyword}%" for keyword in case.broad_keywords]

    sql = """
    SELECT
        collection,
        document_id,
        source_id,
        source_type,
        title,
        text,
        metadata
    FROM a_part_rag_documents
    WHERE dataset_version = %s
      AND (
            COALESCE(title, '') ILIKE ANY(%s)
         OR COALESCE(text, '') ILIKE ANY(%s)
         OR COALESCE(metadata::text, '') ILIKE ANY(%s)
      )
    LIMIT %s;
    """

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                [
                    DATASET_VERSION,
                    patterns,
                    patterns,
                    patterns,
                    limit,
                ],
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
            "metadata": row[6],
            "similarity": None,
            "rerank_score": None,
        }
        for row in rows
    ]


def _build_composite_direct_candidate(
    case: GapCase,
    analyzed_candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """여러 공식 문서가 질문의 필수 근거 그룹을 나누어 설명하면 복합 직접 근거로 묶는다."""
    if not case.allow_composite:
        return None

    required_indexes = set(range(len(case.required_groups)))
    covered: set[int] = set()
    selected: list[dict[str, Any]] = []
    remaining = [
        item
        for item in analyzed_candidates
        if item.get("body_matched_group_count", 0) > 0
    ]

    while remaining and covered != required_indexes:
        remaining.sort(
            key=lambda item: (
                len(
                    {
                        index
                        for index, hits in enumerate(
                            item.get("body_matched_groups") or []
                        )
                        if hits
                    }
                    - covered
                ),
                float(item.get("rerank_score") or 0.0),
                float(item.get("similarity") or 0.0),
            ),
            reverse=True,
        )
        picked = remaining.pop(0)
        new_groups = {
            index
            for index, hits in enumerate(
                picked.get("body_matched_groups") or []
            )
            if hits
        } - covered
        if not new_groups:
            continue
        selected.append(picked)
        covered.update(new_groups)

    if covered != required_indexes or len(selected) < 2:
        return None

    component_ids = [str(item.get("document_id") or "") for item in selected]
    component_titles = [str(item.get("title") or "") for item in selected]
    first_rank = min(
        [int(item["rank"]) for item in selected if item.get("rank") is not None]
        or [0]
    )

    return {
        "rank": first_rank or None,
        "collection": "composite_official_sources",
        "document_id": "composite:" + "|".join(component_ids),
        "source_id": "|".join(
            str(item.get("source_id") or "") for item in selected
        ),
        "source_type": "composite",
        "title": " + ".join(component_titles),
        "issue_id": None,
        "similarity": max(
            float(item.get("similarity") or 0.0) for item in selected
        ),
        "rerank_score": max(
            float(item.get("rerank_score") or 0.0) for item in selected
        ),
        "text_preview": "여러 공식 원문이 필수 근거 역할을 나누어 충족함",
        "body_matched_groups": [
            ["복합 공식 근거 충족"] for _ in case.required_groups
        ],
        "body_matched_group_count": len(case.required_groups),
        "topic_matched_groups": [],
        "topic_matched_group_count": 0,
        "weak_keyword_hits": [],
        "substantive_body_preview": "",
        "composite": True,
        "component_document_ids": component_ids,
        "component_titles": component_titles,
        "component_candidates": selected,
    }


def _analyze_candidates(
    case: GapCase,
    candidates: list[dict[str, Any]],
    include_rank: bool,
) -> dict[str, Any]:
    direct: list[dict[str, Any]] = []
    weak: list[dict[str, Any]] = []
    all_analyzed: list[dict[str, Any]] = []

    for index, result in enumerate(candidates, start=1):
        body_text = _substantive_body(result)
        topic_text = _candidate_topic_text(result)

        body_group_hits = _matched_groups(
            body_text,
            case.required_groups,
        )
        topic_group_hits = _matched_groups(
            topic_text,
            case.required_groups,
        )
        weak_keyword_hits = _weak_hits(
            topic_text,
            case.weak_keywords,
        )

        analyzed = {
            **_result_summary(
                result,
                rank=index if include_rank else None,
            ),
            "body_matched_groups": body_group_hits,
            "body_matched_group_count": _matched_group_count(
                body_group_hits
            ),
            "topic_matched_groups": topic_group_hits,
            "topic_matched_group_count": _matched_group_count(
                topic_group_hits
            ),
            "weak_keyword_hits": weak_keyword_hits,
            "substantive_body_preview": (
                body_text[:700]
                + ("..." if len(body_text) > 700 else "")
            ),
        }

        all_analyzed.append(analyzed)

        if _all_groups_matched(body_group_hits):
            direct.append(analyzed)
        elif (
            _matched_group_count(body_group_hits) >= 2
            or _matched_group_count(topic_group_hits) >= 2
            or weak_keyword_hits
        ):
            weak.append(analyzed)

    composite = _build_composite_direct_candidate(
        case,
        all_analyzed,
    )
    if not direct and composite is not None:
        direct.append(composite)

    direct.sort(
        key=lambda item: (
            item["body_matched_group_count"],
            float(item.get("rerank_score") or 0.0),
            float(item.get("similarity") or 0.0),
        ),
        reverse=True,
    )
    weak.sort(
        key=lambda item: (
            item["body_matched_group_count"],
            item["topic_matched_group_count"],
            len(item["weak_keyword_hits"]),
            float(item.get("rerank_score") or 0.0),
            float(item.get("similarity") or 0.0),
        ),
        reverse=True,
    )

    return {"direct": direct, "weak": weak}


def _classify_gap(
    semantic_analysis: dict[str, Any],
    db_analysis: dict[str, Any],
) -> tuple[str, str, str]:
    if semantic_analysis["direct"]:
        return (
            "BODY_DIRECT_IN_TOP30",
            "검색·선택 기준 보완",
            (
                "실제 본문 직접 근거가 상위 30개 안에 있습니다. "
                "추가 수집보다 answer evidence 선택, rerank, "
                "chunk 선택 기준을 먼저 점검해야 합니다."
            ),
        )

    if db_analysis["direct"]:
        return (
            "BODY_DIRECT_OUTSIDE_TOP30",
            "routing·rerank 보완",
            (
                "DB 전체에는 실제 본문 직접 근거가 있지만 의미 검색 상위 30개에 "
                "들어오지 않았습니다. 추가 수집보다 routing·rerank·metadata "
                "보완이 우선입니다."
            ),
        )

    if semantic_analysis["weak"] or db_analysis["weak"]:
        return (
            "BODY_WEAK_ONLY",
            "기존 원문 재청크·서비스 카드 보완",
            (
                "제목·metadata·일부 본문은 관련되지만 실제 본문이 질문 전체를 직접 뒷받침하지 못합니다. "
                "기존 원문의 필요한 부분을 재청크하거나 공식 원문 기반의 "
                "서비스용 근거 카드를 추가하는 것이 우선입니다."
            ),
        )

    return (
        "NO_BODY_EVIDENCE",
        "주제별 추가 수집 검토",
        (
            "현재 dataset_version의 DB에서 질문 전체를 뒷받침하는 실제 본문 근거를 찾지 못했습니다. "
            "공식 원문이 기존 수집 폴더에도 없는지 확인한 뒤 해당 주제만 "
            "추가 수집해야 합니다."
        ),
    )


def _dedupe_by_document_id(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []

    for item in items:
        document_id = str(item.get("document_id") or "")
        if document_id in seen:
            continue
        seen.add(document_id)
        deduped.append(item)

    return deduped


def main() -> None:
    print(
        "검색 코드 버전:",
        getattr(retriever_module, "CODE_VERSION", "버전 정보 없음"),
    )
    print("dataset_version:", DATASET_VERSION)
    print("진단 질문 수:", len(GAP_CASES))
    print()

    results: list[dict[str, Any]] = []
    summary_counts = {
        "BODY_DIRECT_IN_TOP30": 0,
        "BODY_DIRECT_OUTSIDE_TOP30": 0,
        "BODY_WEAK_ONLY": 0,
        "NO_BODY_EVIDENCE": 0,
        "ERROR": 0,
    }

    for index, case in enumerate(GAP_CASES, start=1):
        print("=" * 100)
        print(f"[{index}/{len(GAP_CASES)}] {case.question_id}")
        print("질문:", case.question)
        print("근거 주제:", case.topic)
        print("-" * 100)

        try:
            semantic_results = _semantic_search(case)
            db_results = _db_lexical_scan(case)

            semantic_analysis = _analyze_candidates(
                case,
                semantic_results,
                include_rank=True,
            )
            db_analysis = _analyze_candidates(
                case,
                db_results,
                include_rank=False,
            )

            semantic_analysis["direct"] = _dedupe_by_document_id(
                semantic_analysis["direct"]
            )
            semantic_analysis["weak"] = _dedupe_by_document_id(
                semantic_analysis["weak"]
            )
            db_analysis["direct"] = _dedupe_by_document_id(
                db_analysis["direct"]
            )
            db_analysis["weak"] = _dedupe_by_document_id(
                db_analysis["weak"]
            )

            classification, action, explanation = _classify_gap(
                semantic_analysis,
                db_analysis,
            )
            summary_counts[classification] += 1

            print("진단:", classification)
            print("권장 조치:", action)
            print("상위 30개 본문 직접 근거:", len(semantic_analysis["direct"]))
            print("DB 전체 본문 직접 근거:", len(db_analysis["direct"]))
            print(
                "관련 있지만 약한 근거:",
                max(
                    len(semantic_analysis["weak"]),
                    len(db_analysis["weak"]),
                ),
            )

            if semantic_analysis["direct"]:
                first = semantic_analysis["direct"][0]
                if first.get("composite"):
                    print(
                        "상위 30개 복합 공식 근거:",
                        " | ".join(first["component_document_ids"]),
                    )
                else:
                    print(
                        "최상위 본문 직접 후보:",
                        f"{first['rank']}위 / "
                        f"{first['document_id']} / "
                        f"{first['title']}",
                    )
            elif db_analysis["direct"]:
                first = db_analysis["direct"][0]
                print(
                    "DB 본문 직접 후보:",
                    f"{first['document_id']} / "
                    f"{first['title']}",
                )

            results.append(
                {
                    "question_id": case.question_id,
                    "question": case.question,
                    "topic": case.topic,
                    "classification": classification,
                    "recommended_action": action,
                    "explanation": explanation,
                    "semantic_result_count": len(semantic_results),
                    "db_lexical_result_count": len(db_results),
                    "semantic_direct_count": len(
                        semantic_analysis["direct"]
                    ),
                    "semantic_weak_count": len(
                        semantic_analysis["weak"]
                    ),
                    "db_direct_count": len(db_analysis["direct"]),
                    "db_weak_count": len(db_analysis["weak"]),
                    "semantic_direct_candidates": (
                        semantic_analysis["direct"][:10]
                    ),
                    "semantic_weak_candidates": (
                        semantic_analysis["weak"][:10]
                    ),
                    "db_direct_candidates": db_analysis["direct"][:20],
                    "db_weak_candidates": db_analysis["weak"][:20],
                }
            )

        except Exception as error:
            summary_counts["ERROR"] += 1
            print("진단: ERROR")
            print("오류:", repr(error))

            results.append(
                {
                    "question_id": case.question_id,
                    "question": case.question,
                    "topic": case.topic,
                    "classification": "ERROR",
                    "recommended_action": "오류 확인",
                    "explanation": repr(error),
                    "semantic_result_count": 0,
                    "db_lexical_result_count": 0,
                    "semantic_direct_count": 0,
                    "semantic_weak_count": 0,
                    "db_direct_count": 0,
                    "db_weak_count": 0,
                    "semantic_direct_candidates": [],
                    "semantic_weak_candidates": [],
                    "db_direct_candidates": [],
                    "db_weak_candidates": [],
                }
            )

        print()

    print("=" * 100)
    print("실제 본문 근거 갭 진단 요약")
    print("-" * 100)
    for key in [
        "BODY_DIRECT_IN_TOP30",
        "BODY_DIRECT_OUTSIDE_TOP30",
        "BODY_WEAK_ONLY",
        "NO_BODY_EVIDENCE",
        "ERROR",
    ]:
        print(f"{key}: {summary_counts[key]}개")

    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    JSON_PATH.write_text(
        json.dumps(
            {
                "search_code_version": getattr(
                    retriever_module,
                    "CODE_VERSION",
                    None,
                ),
                "dataset_version": DATASET_VERSION,
                "question_count": len(GAP_CASES),
                "summary": summary_counts,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    with CSV_PATH.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "question_id",
                "topic",
                "classification",
                "recommended_action",
                "semantic_direct_count",
                "db_direct_count",
                "semantic_weak_count",
                "db_weak_count",
            ],
        )
        writer.writeheader()

        for item in results:
            writer.writerow(
                {
                    "question_id": item["question_id"],
                    "topic": item["topic"],
                    "classification": item["classification"],
                    "recommended_action": item["recommended_action"],
                    "semantic_direct_count": item[
                        "semantic_direct_count"
                    ],
                    "db_direct_count": item["db_direct_count"],
                    "semantic_weak_count": item[
                        "semantic_weak_count"
                    ],
                    "db_weak_count": item["db_weak_count"],
                }
            )

    print(f"\nJSON 결과 저장: {JSON_PATH}")
    print(f"CSV 요약 저장: {CSV_PATH}")


if __name__ == "__main__":
    main()