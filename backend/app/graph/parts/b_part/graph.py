"""
B파트 계약 중 분쟁 MVP 그래프.

FastAPI 라우터가 기대하는 graph.ainvoke(request) 인터페이스를 유지하면서,
내부 실행은 LangGraph StateGraph를 통해 수행합니다.

현재 1차 전환에서는 기존 B파트 파이프라인을 StateGraph의 호환 노드로 감싸고,
후속 작업에서 Context Resolver, Intent Planner, Rule Engine, Retriever 등을
개별 노드로 점진 분리할 수 있게 구조를 마련합니다.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.llm.b_part import generate_b_part_answer, stream_text
from app.llm.b_part_context import analyze_b_part_context
from app.llm.b_part_intent import analyze_b_part_intent
from app.llm.b_part_planner import analyze_b_part_plan
from app.llm.b_part_scope import analyze_b_part_scope
from app.rag.retrievers.b_part import BPartRetriever
from app.graph.parts.b_part.calendar_events import (
    build_calendar_event_candidates,
    build_calendar_pending_action,
    build_calendar_registration_ready_action,
    format_calendar_events_for_answer,
)
from app.graph.parts.b_part.calendar_tool import run_calendar_registration
from app.graph.parts.b_part.memory import (
    build_contextual_question,
    extract_conversation_id,
    build_history_text,
    memory_store,
)
from app.graph.parts.b_part.planner_validator import validate_planner_flow
from app.graph.parts.b_part.rules import (
    has_date_in_text,
    parse_day_from_text,
    parse_money_values_from_text,
    parse_year_month_from_text,
    run_b_part_rules,
)


RETRIEVAL_MIN_TOP_SIMILARITY = 0.27
RENEWAL_SLOT_CATEGORIES = {"계약갱신", "계약갱신요구권", "묵시적갱신"}
PRECEDENT_MIN_SIMILARITY = 0.34

CORE_LAW_ANCHORS = {
    "계약갱신": [
        ("주택임대차보호법", "4"),
        ("주택임대차보호법", "6"),
    ],
    "계약갱신요구권": [
        ("주택임대차보호법", "6의3"),
    ],
    "묵시적갱신": [
        ("주택임대차보호법", "6"),
        ("주택임대차보호법", "6의2"),
    ],
    "차임증감": [
        ("주택임대차보호법", "7"),
        ("민법", "628"),
    ],
    "전월세전환": [
        ("주택임대차보호법", "7의2"),
        ("주택임대차보호법 시행령", "9"),
    ],
    "임대인의무": [
        ("민법", "623"),
        ("민법", "624"),
    ],
    "수선의무": [
        ("민법", "623"),
        ("민법", "626"),
        ("민법", "627"),
    ],
    "계약해지": [
        ("민법", "627"),
        ("민법", "635"),
        ("민법", "640"),
    ],
    "손해배상": [
        ("민법", "623"),
        ("민법", "625"),
    ],
}

B_PART_CATEGORIES = [
    "계약갱신",
    "계약갱신요구권",
    "묵시적갱신",
    "차임증감",
    "전월세전환",
    "임대인의무",
    "수선의무",
    "계약해지",
    "손해배상",
]

CATEGORY_KEYWORDS = {
    "계약갱신요구권": [
        "갱신요구",
        "계약갱신요구권",
        "실거주",
        "갱신 거절",
        "갱신거절",
        "나가라고",
        "연장 거절",
    ],
    "묵시적갱신": ["묵시", "자동연장", "자동 연장", "아무 말", "만료됐는데", "기간이 지났"],
    "차임증감": ["월세", "차임", "임대료", "인상", "올려", "증액", "감액", "5%"],
    "전월세전환": ["전세를 월세", "월세로 전환", "반전세", "전월세전환", "전환율"],
    "수선의무": ["수리", "고장", "누수", "보일러", "곰팡이", "결로", "배관", "하자"],
    "임대인의무": ["못 살", "사용", "수익", "방해", "거주", "집주인 의무", "임대인 의무"],
    "계약해지": ["해지", "중도해지", "나가고 싶", "계약을 끝", "연체", "밀렸"],
    "손해배상": ["손해배상", "배상", "파손", "망가", "피해", "손해"],
    "계약갱신": ["계약 연장", "재계약", "계약갱신", "연장 가능", "만료 전"],
}

CATEGORY_GROUPS = {
    "수선의무": ["수선의무", "임대인의무", "계약해지", "손해배상"],
    "계약해지": ["계약해지", "수선의무", "임대인의무", "손해배상"],
    "손해배상": ["손해배상", "수선의무", "임대인의무", "계약해지"],
    "차임증감": ["차임증감", "전월세전환"],
    "전월세전환": ["전월세전환", "차임증감"],
    "계약갱신요구권": ["계약갱신요구권", "계약갱신", "묵시적갱신"],
    "계약갱신": ["계약갱신", "계약갱신요구권", "묵시적갱신"],
    "묵시적갱신": ["묵시적갱신", "계약갱신", "계약갱신요구권"],
}

OUT_OF_SCOPE_RULES = [
    {
        "reason": "계약 전/전세사기 위험 분석",
        "patterns": [
            r"전세\s*사기",
            r"깡통\s*전세",
            r"등기부\s*등본",
            r"신탁",
            r"선순위",
            r"근저당",
            r"전입\s*신고\s*전",
            r"계약\s*전",
        ],
    },
    {
        "reason": "계약 종료 후/보증금 반환",
        "patterns": [
            r"보증금.*(반환|안\s*줘|안\s*주|안\s*돌려|못\s*받|돌려주지|돈\s*안|돈을\s*안|돈\s*주지)",
            r"임차권\s*등기\s*명령",
            r"임차권\s*등기",
        ],
    },
    {
        "reason": "권리분석/경매·배당",
        "patterns": [
            r"대항력",
            r"우선\s*변제권",
            r"최우선\s*변제권",
            r"경매",
            r"배당",
            r"확정\s*일자\s*순위",
        ],
    },
    {
        "reason": "계약 종료 후/명도·원상회복",
        "patterns": [
            r"명도",
            r"원상\s*회복",
            r"퇴거\s*후",
            r"이사\s*후",
        ],
    },
    {
        "reason": "비주택 임대차",
        "patterns": [
            r"상가",
            r"점포",
            r"사무실",
            r"공장",
            r"토지\s*임대차",
        ],
    },
]


def extract_user_question(request: dict[str, Any]) -> str:
    """라우터에서 넘어온 여러 형태의 요청에서 사용자 질문을 꺼냅니다."""
    for key in ("message", "query", "question", "input", "content", "text"):
        value = request.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    messages = request.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()

    raise ValueError("계약 중에 관련된 질문을 찾지 못했습니다. message 또는 query 값을 보내주세요.")


def detect_categories(question: str) -> list[str]:
    """키워드 기반 1차 의도 분류입니다. 이후 LLM Intent Analyzer로 교체할 수 있습니다."""
    scores: dict[str, int] = {}
    for category, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in question)
        if score:
            scores[category] = score

    if not scores:
        return []

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    primary = ranked[0][0]
    categories = CATEGORY_GROUPS.get(primary, [primary])

    for category, _score in ranked[1:]:
        if category not in categories:
            categories.append(category)

    return [category for category in categories if category in B_PART_CATEGORIES]


def has_schedule_signal(question: str) -> bool:
    """
    갱신 일정/캘린더 계산 의도가 있는지 가볍게 감지합니다.

    이 함수는 최종 분류기가 아니라 LLM Intent Analyzer를 보조 호출할지
    판단하기 위한 신호 감지용입니다.
    """
    has_date = has_date_in_text(question)
    has_schedule_word = any(
        keyword in question
        for keyword in [
            "계약 종료일",
            "계약 만료일",
            "종료일",
            "만료일",
            "갱신",
            "언제부터",
            "일정",
            "캘린더",
            "등록",
        ]
    )
    return has_date and has_schedule_word


def detect_out_of_scope_reason(question: str) -> dict[str, Any] | None:
    """B파트 담당 범위를 벗어난 질문인지 먼저 확인합니다."""
    for rule in OUT_OF_SCOPE_RULES:
        if any(re.search(pattern, question) for pattern in rule["patterns"]):
            return {
                "is_out_of_scope": True,
                "reason": rule["reason"],
            }

    return None


def should_call_llm_intent(
    question: str,
    categories: list[str],
    rule_results: list[dict[str, Any]],
) -> bool:
    """
    키워드 기반 분류가 비었거나, 일정 신호가 있는데 계산 결과가 없을 때만
    LLM Intent Analyzer를 보조 호출합니다.
    """
    if not categories:
        return True
    if has_schedule_signal(question) and not rule_results:
        return True
    return False


def merge_categories(base_categories: list[str], new_categories: list[str]) -> list[str]:
    """기존 카테고리 순서를 유지하면서 LLM 카테고리를 뒤에 보강합니다."""
    merged = list(base_categories)
    for category in new_categories:
        if category in B_PART_CATEGORIES and category not in merged:
            merged.append(category)
    return merged


def has_repair_timing_info(question: str) -> bool:
    """
    수선의무 질문에서 하자 발생 시점이나 수리 요청 후 경과 기간이 있는지 확인합니다.

    사용자는 "언제부터"처럼 정형화해서 말하지 않고,
    "1주일 지났어", "며칠째야", "계속 안 고쳐줘"처럼 답하는 경우가 많습니다.
    이 함수는 그런 표현을 시간 정보로 인정해 같은 질문을 반복하지 않도록 합니다.
    """
    if any(keyword in question for keyword in ["언제", "며칠", "몇일", "얼마나"]):
        return True

    if re.search(r"\d+\s*(일|주|주일|개월|달|년)", question):
        return True

    return any(
        keyword in question
        for keyword in [
            "일주일",
            "한 주",
            "한달",
            "한 달",
            "지났",
            "지난",
            "째",
            "계속",
            "아직",
            "요청 후",
            "요청한 뒤",
            "요청했는데",
            "안 고쳐",
            "안 해줘",
        ]
    )


def find_missing_questions(question: str, categories: list[str]) -> list[str]:
    """계산이나 판단에 필요한 핵심 정보가 빠졌을 때 추가 질문을 만듭니다."""
    missing: list[str] = []
    has_date = has_date_in_text(question)
    has_repair_signal = any(
        keyword in question
        for keyword in ["수리", "고장", "누수", "보일러", "곰팡이", "결로", "배관", "하자"]
    )

    money_values = parse_money_values_from_text(question)
    has_two_money_values = len(money_values) >= 2

    if any(category in categories for category in ["계약갱신", "계약갱신요구권", "묵시적갱신"]):
        if not has_date:
            missing.append("계약 종료일과 집주인 또는 세입자가 통보한 날짜가 언제인지 알려주세요.")

    if any(category in categories for category in ["차임증감", "전월세전환"]):
        if not has_two_money_values:
            missing.append("현재 월세와 집주인이 요구한 월세가 각각 얼마인지 알려주세요.")
        if "최근" not in question and "1년" not in question:
            missing.append("최근 1년 안에 보증금이나 월세를 올린 적이 있는지 알려주세요.")

    if has_repair_signal and any(category in categories for category in ["수선의무", "임대인의무", "계약해지", "손해배상"]):
        if "문자" not in question and "카톡" not in question and "증거" not in question:
            missing.append("집주인에게 수리를 요청한 문자, 카카오톡, 사진 같은 증거가 있는지 알려주세요.")
        if not has_repair_timing_info(question):
            missing.append("하자가 언제부터 있었고, 수리 요청 후 얼마나 지났는지 알려주세요.")

    return missing[:3]


def deduplicate_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """여러 카테고리 검색 결과에서 같은 청크가 중복되는 것을 제거합니다."""
    seen: set[str] = set()
    unique_results: list[dict[str, Any]] = []
    for result in results:
        metadata = result.get("metadata") or {}
        key = str(metadata.get("chunk_id") or result.get("id"))
        if key in seen:
            continue
        seen.add(key)
        unique_results.append(result)
    return unique_results


def normalize_article_token(value: Any) -> str:
    """조문 번호 비교를 위해 '제6조의3', '6의3', '6 3' 같은 표현을 단순화합니다."""
    text = str(value or "")
    text = text.replace("제", "").replace("조", "").replace("의", "-")
    text = re.sub(r"[^0-9-]", "", text)
    return text.strip("-")


def is_core_law_anchor(result: dict[str, Any], law_keyword: str, article: str) -> bool:
    """검색 결과가 category별 핵심 조문 anchor와 일치하는지 확인합니다."""
    metadata = result.get("metadata") or {}
    law_name = str(metadata.get("law_name") or "")
    title = str(result.get("title") or metadata.get("title") or "")
    metadata_article = str(metadata.get("article") or "")
    expected_article = normalize_article_token(article)

    if law_keyword not in law_name and law_keyword not in title:
        return False

    if normalize_article_token(metadata_article) == expected_article:
        return True

    normalized_title = normalize_article_token(title)
    return expected_article in normalized_title


def filter_precedents_by_similarity(
    results: list[dict[str, Any]],
    min_similarity: float = PRECEDENT_MIN_SIMILARITY,
) -> list[dict[str, Any]]:
    """관련성이 약한 판례가 최종 근거에 섞이지 않도록 similarity 기준으로 제외합니다."""
    filtered: list[dict[str, Any]] = []
    for result in results:
        try:
            similarity = float(result.get("similarity") or 0)
        except (TypeError, ValueError):
            similarity = 0.0
        if similarity >= min_similarity:
            filtered.append(result)
    return filtered


def evaluate_retrieval_quality(retrieved: list[dict[str, Any]]) -> dict[str, Any]:
    """검색 결과가 답변 생성에 충분한지 가볍게 판단합니다."""
    similarities = [
        float(result.get("similarity", 0) or 0)
        for result in retrieved
    ]
    max_similarity = max(similarities, default=0.0)
    average_similarity = (
        round(sum(similarities) / len(similarities), 4)
        if similarities
        else 0.0
    )

    if not retrieved:
        return {
            "is_weak": True,
            "reason": "검색 결과가 없습니다.",
            "max_similarity": 0.0,
            "average_similarity": 0.0,
            "threshold": RETRIEVAL_MIN_TOP_SIMILARITY,
        }

    is_weak = max_similarity < RETRIEVAL_MIN_TOP_SIMILARITY
    reason = (
        "Top-1 similarity가 기준보다 낮습니다."
        if is_weak
        else "검색 결과가 기준을 통과했습니다."
    )

    return {
        "is_weak": is_weak,
        "reason": reason,
        "max_similarity": round(max_similarity, 4),
        "average_similarity": average_similarity,
        "threshold": RETRIEVAL_MIN_TOP_SIMILARITY,
    }


def should_refine_intent_after_retrieval(
    retrieval_quality: dict[str, Any],
    intent_result: dict[str, Any] | None,
) -> bool:
    """검색 결과가 약하고 아직 LLM 보완을 하지 않았을 때 재분류를 시도합니다."""
    if not retrieval_quality.get("is_weak"):
        return False
    if intent_result and intent_result.get("source") == "llm":
        return False
    return True


def should_call_scope_analyzer(question: str, categories: list[str]) -> bool:
    """카테고리가 잡히지 않는 질문은 B파트 범위인지 먼저 확인합니다."""
    if categories:
        return False
    if has_schedule_signal(question):
        return False
    return True


def build_scope_guidance_answer(scope_result: dict[str, Any]) -> str:
    """범위 밖 또는 애매한 질문에 대한 안내 답변을 만듭니다."""
    scope = scope_result.get("scope")
    reason = scope_result.get("reason") or "질문만으로는 B파트 범위인지 판단하기 어렵습니다."
    clarification_question = (
        scope_result.get("clarification_question")
        or "주택임대차 계약 중 어떤 문제인지 조금 더 구체적으로 알려주세요."
    )

    if scope == "out_of_scope":
        return (
            "이 질문은 현재 계약 중 범위인 '주택임대차 계약 중 분쟁'에는 포함되지 않을 가능성이 큽니다.\n\n"
            f"판단 이유: {reason}\n\n"
            "계약 중 범위에서는 실제 거주 중 발생하는 계약갱신, 계약갱신요구권, 묵시적 갱신, "
            "월세·보증금 증감, 전월세전환, 임대인의무, 수선의무, 계약 중도해지, "
            "계약 중 손해배상 문제를 다룹니다."
        )

    return (
        "현재 질문만으로는 계약 중 범위인 '주택임대차 계약 중 분쟁'에 해당하는지 판단하기 어렵습니다.\n\n"
        f"판단 이유: {reason}\n\n"
        "계약 중 범위에서는 다음 문제를 다룹니다.\n"
        "- 계약갱신 또는 계약갱신요구권\n"
        "- 묵시적 갱신\n"
        "- 월세·보증금 인상 또는 감액\n"
        "- 전월세전환\n"
        "- 임대인의 수선의무\n"
        "- 계약 중도해지\n"
        "- 계약 중 손해배상\n\n"
        f"{clarification_question}"
    )


def has_renewal_slot_context(
    question: str,
    categories: list[str],
    context_result: dict[str, Any],
) -> bool:
    """계약 종료일 슬롯을 채워야 하는 갱신 계열 질문인지 확인합니다."""
    category_set = set(categories or []) | set(context_result.get("categories") or [])
    if category_set & RENEWAL_SLOT_CATEGORIES:
        return True

    return any(
        keyword in question
        for keyword in [
            "계약 종료",
            "계약 만료",
            "종료일",
            "만료일",
            "갱신",
            "자동 연장",
            "자동연장",
            "묵시적",
        ]
    )


def build_contract_end_day_question(year: int, month: int) -> str:
    """연월까지만 확인된 계약 종료일에 대해 일자를 다시 묻습니다."""
    return (
        f"{year}년 {month}월까지는 확인했습니다. "
        f"계약 종료일이 {year}년 {month}월 며칠인지 알려주세요. "
        "계약갱신요구 기간과 묵시적 갱신 여부는 정확한 일자가 있어야 계산할 수 있습니다."
    )


def is_contract_end_date_clarification(question: str) -> bool:
    """사용자가 '계약 종료일이 언제냐'고 되묻는 상황인지 확인합니다."""
    return (
        "계약 종료일" in question
        and any(keyword in question for keyword in ["언제", "뭐", "무엇", "알려"])
    )


def build_planner_missing_questions(planner_result: dict[str, Any]) -> list[str]:
    """Planner가 판단한 필수 누락 정보를 사용자 질문 문장으로 바꿉니다."""
    missing_facts = planner_result.get("missing_required_facts")
    if not isinstance(missing_facts, list):
        return []

    question_map = {
        "contract_end_date": "계약 종료일이 언제인지 알려주세요.",
        "contract_notice_date": "집주인 또는 세입자가 갱신 거절이나 조건 변경을 통보한 날짜가 언제인지 알려주세요.",
        "current_rent": "현재 월세가 얼마인지 알려주세요.",
        "requested_rent": "집주인이 요구한 월세가 얼마인지 알려주세요.",
        "recent_rent_increase": "최근 1년 안에 보증금이나 월세를 올린 적이 있는지 알려주세요.",
        "converted_deposit_amount": "월세로 전환하려는 보증금 금액이 얼마인지 알려주세요.",
        "repair_request_date": "집주인에게 수리를 요청한 날짜나 수리 요청 후 경과 기간을 알려주세요.",
        "repair_evidence": "집주인에게 수리를 요청한 문자, 카카오톡, 사진 같은 증거가 있는지 알려주세요.",
        "defect_detail": "어떤 하자나 고장이 있는지 구체적으로 알려주세요.",
    }

    questions: list[str] = []
    for fact in missing_facts:
        key = str(fact).strip()
        question = question_map.get(key)
        if not question:
            question = f"{key} 정보를 알려주세요."
        if question not in questions:
            questions.append(question)
    return questions[:3]


def can_continue_with_rule_results(question: str, categories: list[str]) -> bool:
    """
    일부 부가 정보가 부족해도 Rule Engine 계산이 가능한 질문인지 판단합니다.

    예를 들어 월세 인상 질문에서 현재 월세와 요구 월세가 모두 있으면
    계약 종료일이 없어도 5% 초과 여부는 계산할 수 있으므로 답변 흐름을 계속 진행합니다.
    또한 누수로 인한 물건 파손처럼 하자와 손해가 함께 드러난 질문은
    증거 여부가 없어도 기본 법률 구조를 먼저 설명할 수 있습니다.
    """
    if "차임증감" in categories and len(parse_money_values_from_text(question)) >= 2:
        return True
    has_defect = any(keyword in question for keyword in ["누수", "보일러", "곰팡이", "결로", "배관", "하자"])
    has_damage = any(keyword in question for keyword in ["망가", "파손", "손해", "손해배상", "피해"])
    if has_defect and has_damage:
        return True
    return False


class BPartGraphState(TypedDict, total=False):
    """B파트 LangGraph 실행 상태입니다."""

    request: dict[str, Any]
    original_question: str
    question: str
    conversation_id: str | None
    history_messages: list[dict[str, Any]]
    history_text: str
    context_result: dict[str, Any]
    memory_meta: dict[str, Any]
    categories: list[str]
    keyword_categories: list[str]
    planner_result: dict[str, Any]
    planner_validation: dict[str, Any]
    scope_result: dict[str, Any] | None
    intent_result: dict[str, Any] | None
    rule_results: list[dict[str, Any]]
    calendar_events: list[dict[str, Any]]
    pending_action: dict[str, Any] | None
    calendar_tool_result: dict[str, Any] | None
    executed_tools: list[str]
    skipped_tools: list[str]
    top_k: int
    retrieved: list[dict[str, Any]]
    retrieval_quality: dict[str, Any]
    final_state: dict[str, Any]


class BPartMVPGraph:
    """FastAPI 라우터와 호환되는 B파트 LangGraph 어댑터입니다."""

    def __init__(self) -> None:
        self.retriever = BPartRetriever()
        self._compiled_graph = self._build_state_graph()

    def _build_state_graph(self):
        """B파트 처리 흐름을 LangGraph StateGraph로 컴파일합니다."""
        builder = StateGraph(BPartGraphState)
        builder.add_node("prepare_context", self._prepare_context_node)
        builder.add_node("check_keyword_scope", self._check_keyword_scope_node)
        builder.add_node("handle_calendar_confirmation", self._handle_calendar_confirmation_node)
        builder.add_node("plan", self._plan_node)
        builder.add_node("validate_plan", self._validate_plan_node)
        builder.add_node("missing_scope", self._missing_scope_node)
        builder.add_node("compute", self._compute_node)
        builder.add_node("retrieve", self._retrieve_node)
        builder.add_node("answer", self._answer_node)
        builder.add_edge(START, "prepare_context")
        builder.add_edge("prepare_context", "check_keyword_scope")
        builder.add_conditional_edges(
            "check_keyword_scope",
            self._route_after_keyword_scope,
            {
                "end": END,
                "continue": "handle_calendar_confirmation",
            },
        )
        builder.add_conditional_edges(
            "handle_calendar_confirmation",
            self._route_after_calendar_confirmation,
            {
                "end": END,
                "continue": "plan",
            },
        )
        builder.add_edge("plan", "validate_plan")
        builder.add_edge("validate_plan", "missing_scope")
        builder.add_conditional_edges(
            "missing_scope",
            self._route_after_missing_scope,
            {
                "end": END,
                "continue": "compute",
            },
        )
        builder.add_edge("compute", "retrieve")
        builder.add_edge("retrieve", "answer")
        builder.add_edge("answer", END)
        return builder.compile()

    async def ainvoke(self, request: dict[str, Any]) -> dict[str, Any]:
        """외부 호출 인터페이스는 유지하고 내부적으로 LangGraph를 실행합니다."""
        state = await self._compiled_graph.ainvoke({"request": request})
        return state["final_state"]

    async def _prepare_context_node(self, state: BPartGraphState) -> BPartGraphState:
        """LangGraph 노드: 사용자 입력과 이전 대화 맥락을 정리합니다."""
        request = state.get("request", {})
        original_question = extract_user_question(request)
        conversation_id = extract_conversation_id(request)
        history_messages = (
            memory_store.get_messages(conversation_id)
            if conversation_id
            else []
        )
        history_text = build_history_text(history_messages)
        question, memory_meta = build_contextual_question(
            current_question=original_question,
            history_messages=history_messages,
        )

        context_result = analyze_b_part_context(
            current_message=original_question,
            history_text=history_text,
            fallback_question=question,
        )
        if context_result.get("source") == "llm":
            question = context_result.get("resolved_question") or question
            memory_meta["used_memory"] = bool(
                memory_meta.get("used_memory")
                or context_result.get("is_followup")
            )
            memory_meta["reason"] = (
                "llm_context_resolver"
                if context_result.get("is_followup")
                else memory_meta.get("reason")
            )

        memory_meta["conversation_id"] = conversation_id
        memory_meta["original_question"] = original_question
        memory_meta["contextual_question"] = question
        if conversation_id:
            memory_meta["state"] = memory_store.get_state(conversation_id)

        return {
            **state,
            "original_question": original_question,
            "question": question,
            "conversation_id": conversation_id,
            "history_messages": history_messages,
            "history_text": history_text,
            "context_result": context_result,
            "memory_meta": memory_meta,
        }

    async def _check_keyword_scope_node(self, state: BPartGraphState) -> BPartGraphState:
        """LangGraph 노드: 명확한 B파트 범위 밖 질문을 빠르게 종료합니다."""
        original_question = state["original_question"]
        question = state["question"]
        conversation_id = state.get("conversation_id")
        context_result = state["context_result"]
        memory_meta = state["memory_meta"]

        out_of_scope = (
            detect_out_of_scope_reason(original_question)
            or detect_out_of_scope_reason(question)
        )
        if not out_of_scope:
            return state

        answer = (
            "이 질문은 현재 계약 중 범위인 '주택임대차 계약 중 분쟁'에는 포함되지 않습니다.\n\n"
            f"감지된 범위 밖 주제: {out_of_scope['reason']}\n\n"
            "계약 중 범위에서는 실제 거주 중 발생하는 계약갱신, 계약갱신요구권, 묵시적 갱신, "
            "월세·보증금 증감, 전월세전환, 임대인의무, 수선의무, 계약 중도해지, "
            "계약 중 손해배상 문제를 다룹니다."
        )

        final_state = {
            "question": question,
            "categories": [],
            "context_result": context_result,
            "planner_result": None,
            "intent_result": None,
            "scope_result": {
                "source": "keyword",
                "scope": "out_of_scope",
                "reason": out_of_scope["reason"],
                "suggested_categories": [],
                "clarification_question": "",
            },
            "rule_results": [],
            "calendar_events": [],
            "pending_action": None,
            "calendar_registration": None,
            "calendar_tool_result": None,
            "executed_tools": [],
            "skipped_tools": ["rule_engine", "calendar_candidate", "retriever"],
            "missing_questions": [],
            "retrieved": [],
            "retrieval_quality": {
                "is_out_of_scope": True,
                "reason": out_of_scope["reason"],
            },
            "memory": memory_meta,
            "final_answer": answer,
            "response_stream": stream_text(answer),
        }
        self._save_turn(conversation_id, original_question, answer)
        return {**state, "final_state": final_state}

    def _route_after_keyword_scope(self, state: BPartGraphState) -> str:
        """keyword scope 노드 이후 다음 경로를 결정합니다."""
        if state.get("final_state"):
            return "end"
        return "continue"

    async def _handle_calendar_confirmation_node(self, state: BPartGraphState) -> BPartGraphState:
        """LangGraph 노드: 사용자의 캘린더 등록 승인 메시지를 처리합니다."""
        request = state.get("request", {})
        original_question = state["original_question"]
        question = state["question"]
        conversation_id = state.get("conversation_id")
        context_result = state["context_result"]
        memory_meta = state["memory_meta"]

        pending_action = request.get("pending_action")
        if not isinstance(pending_action, dict):
            return state

        calendar_registration = build_calendar_registration_ready_action(pending_action)
        if not calendar_registration:
            return state

        if request.get("calendar_connection_required"):
            calendar_tool_result = {
                "status": "calendar_connection_required",
                "provider": str(request.get("calendar_provider", "smithery_googlecalendar")),
                "reason": "user_calendar_connection_not_found",
                "event_count": len(calendar_registration.get("events", [])),
                "events": calendar_registration.get("events", []),
                "registered_event_count": 0,
                "registered_events": [],
            }
        else:
            calendar_tool_result = run_calendar_registration(
                calendar_registration,
                mode=str(request.get("calendar_mode", "dry_run")),
                provider=str(request.get("calendar_provider", "google_calendar")),
                calendar_id=str(request.get("calendar_id", "primary")),
                connection_id=request.get("calendar_connection_id"),
            )

        if calendar_tool_result.get("status") == "registered":
            answer = "좋습니다. 아래 일정들을 Google Calendar에 등록했습니다."
        elif calendar_tool_result.get("status") == "partial_success":
            registered_count = calendar_tool_result.get("registered_event_count", 0)
            failed_count = calendar_tool_result.get("failed_event_count", 0)
            answer = (
                f"일부 일정만 Google Calendar에 등록했습니다. "
                f"등록 {registered_count}건, 실패 {failed_count}건입니다."
            )
        elif calendar_tool_result.get("status") == "calendar_connection_required":
            answer = (
                "Google Calendar 연결이 필요합니다.\n"
                "캘린더에 등록하려면 먼저 내 계정의 Google Calendar connection을 연결해 주세요."
            )
        elif calendar_tool_result.get("status") == "not_configured":
            answer = (
                "Google Calendar 등록 설정이 아직 완료되지 않았습니다. 연결 상태를 확인해 주세요."
            )
        elif calendar_tool_result.get("status") == "failed":
            answer = "Google Calendar 등록에 실패했습니다. 연결 상태와 권한을 확인해 주세요."
        else:
            answer = "캘린더 등록 요청을 처리했습니다. 등록 결과를 확인해 주세요."

        final_state = {
            "question": question,
            "categories": [],
            "context_result": context_result,
            "planner_result": None,
            "intent_result": None,
            "scope_result": None,
            "rule_results": [],
            "calendar_events": calendar_registration.get("events", []),
            "pending_action": None,
            "calendar_registration": calendar_registration,
            "calendar_tool_result": calendar_tool_result,
            "executed_tools": ["calendar_confirmation"],
            "skipped_tools": ["rule_engine", "calendar_candidate", "retriever"],
            "missing_questions": [],
            "retrieved": [],
            "memory": memory_meta,
            "final_answer": answer,
            "response_stream": stream_text(answer),
        }
        self._save_turn(conversation_id, original_question, answer)
        return {**state, "final_state": final_state}

    def _route_after_calendar_confirmation(self, state: BPartGraphState) -> str:
        """calendar confirmation 노드 이후 다음 경로를 결정합니다."""
        if state.get("final_state"):
            return "end"
        return "continue"

    async def _plan_node(self, state: BPartGraphState) -> BPartGraphState:
        """LangGraph 노드: 질문 의도와 B파트 카테고리를 계획합니다."""
        request = state.get("request", {})
        original_question = state["original_question"]
        question = state["question"]
        history_text = state.get("history_text", "")
        context_result = state["context_result"]

        categories = request.get("categories") or request.get("category")
        if isinstance(categories, str):
            categories = [categories]
        if not categories:
            categories = context_result.get("categories") or detect_categories(question)
        else:
            categories = merge_categories(
                categories,
                context_result.get("categories", []),
            )

        keyword_categories = detect_categories(question)
        planner_result = analyze_b_part_plan(
            current_message=original_question,
            resolved_question=question,
            history_text=history_text,
            context_result=context_result,
            keyword_categories=keyword_categories,
        )
        categories = merge_categories(
            categories,
            planner_result.get("categories", []),
        )

        return {
            **state,
            "categories": categories,
            "keyword_categories": keyword_categories,
            "planner_result": planner_result,
        }

    async def _validate_plan_node(self, state: BPartGraphState) -> BPartGraphState:
        """LangGraph 노드: LLM Planner 결과를 실행 제어용 결정값으로 검증합니다."""
        planner_validation = validate_planner_flow(
            question=state["question"],
            categories=state.get("categories", []),
            context_result=state["context_result"],
            planner_result=state["planner_result"],
        )

        return {
            **state,
            "planner_validation": planner_validation,
        }

    async def _compute_node(self, state: BPartGraphState) -> BPartGraphState:
        """LangGraph 노드: Rule Engine 계산과 캘린더 후보 생성을 수행합니다."""
        question = state["question"]
        categories = state.get("categories", [])
        planner_validation = state.get("planner_validation", {})
        tools_to_use = planner_validation.get("tools_to_use", ["rule_engine", "retriever"])
        if not isinstance(tools_to_use, list):
            tools_to_use = ["rule_engine", "retriever"]
        executed_tools = list(state.get("executed_tools", []))
        skipped_tools = list(state.get("skipped_tools", []))

        rule_results: list[dict[str, Any]] = []
        intent_result: dict[str, Any] | None = None

        if "rule_engine" in tools_to_use:
            rule_results = run_b_part_rules(question=question, categories=categories)
            executed_tools.append("rule_engine")

            if should_call_llm_intent(
                question=question,
                categories=categories,
                rule_results=rule_results,
            ):
                intent_result = analyze_b_part_intent(question)
                categories = merge_categories(
                    categories,
                    intent_result.get("categories", []),
                )
                rule_results = run_b_part_rules(question=question, categories=categories)
        else:
            skipped_tools.append("rule_engine")

        calendar_events: list[dict[str, Any]] = []
        pending_action: dict[str, Any] | None = None
        if "calendar_candidate" in tools_to_use:
            calendar_events = build_calendar_event_candidates(rule_results)
            pending_action = build_calendar_pending_action(calendar_events)
            executed_tools.append("calendar_candidate")
        else:
            skipped_tools.append("calendar_candidate")

        return {
            **state,
            "categories": categories,
            "intent_result": intent_result,
            "rule_results": rule_results,
            "calendar_events": calendar_events,
            "pending_action": pending_action,
            "executed_tools": list(dict.fromkeys(executed_tools)),
            "skipped_tools": list(dict.fromkeys(skipped_tools)),
        }

    async def _missing_scope_node(self, state: BPartGraphState) -> BPartGraphState:
        """LangGraph 노드: 추가 정보 요청, 부분 날짜 처리, LLM Scope 확인을 수행합니다."""
        original_question = state["original_question"]
        conversation_id = state.get("conversation_id")
        question = state["question"]
        context_result = state["context_result"]
        memory_meta = state["memory_meta"]
        categories = state.get("categories", [])
        planner_result = state["planner_result"]
        planner_validation = state.get("planner_validation", {})

        memory_state = (
            memory_store.get_state(conversation_id)
            if conversation_id
            else {}
        )
        renewal_slot_context = has_renewal_slot_context(
            question=question,
            categories=categories,
            context_result=context_result,
        )

        if renewal_slot_context and conversation_id:
            pending_year = memory_state.get("pending_contract_end_year")
            pending_month = memory_state.get("pending_contract_end_month")
            pending_field = memory_state.get("pending_field")

            if pending_field == "contract_end_day" and pending_year and pending_month:
                day = parse_day_from_text(original_question)
                if day is not None:
                    try:
                        contract_end_date = date(int(pending_year), int(pending_month), day)
                    except ValueError:
                        answer = (
                            f"{pending_year}년 {pending_month}월에는 {day}일이 없습니다. "
                            "계약서에 적힌 정확한 계약 종료일을 다시 알려주세요."
                        )
                        final_state = self._build_early_final_state(
                            question=question,
                            categories=categories,
                            context_result=context_result,
                            planner_result=planner_result,
                            intent_result=None,
                            scope_result=None,
                            missing_questions=[answer],
                            retrieval_quality={
                                "skipped": True,
                                "reason": "invalid_contract_end_day",
                            },
                            memory_meta={
                                **memory_meta,
                                "state": memory_store.get_state(conversation_id),
                            },
                            answer=answer,
                        )
                        self._save_turn(conversation_id, original_question, answer)
                        return {**state, "final_state": final_state}

                    memory_store.clear_state_fields(
                        conversation_id,
                        [
                            "pending_contract_end_year",
                            "pending_contract_end_month",
                            "pending_field",
                        ],
                    )
                    question = (
                        f"{question}\n\n"
                        f"확정된 계약 종료일: {contract_end_date.isoformat()}"
                    )
                    memory_meta["contextual_question"] = question
                    memory_meta["state"] = memory_store.get_state(conversation_id)
                    memory_meta["resolved_partial_date"] = {
                        "field": "contract_end_date",
                        "value": contract_end_date.isoformat(),
                    }

                elif is_contract_end_date_clarification(original_question):
                    answer = build_contract_end_day_question(
                        int(pending_year),
                        int(pending_month),
                    )
                    final_state = self._build_early_final_state(
                        question=question,
                        categories=categories,
                        context_result=context_result,
                        planner_result=planner_result,
                        intent_result=None,
                        scope_result=None,
                        missing_questions=[answer],
                        retrieval_quality={
                            "skipped": True,
                            "reason": "waiting_for_contract_end_day",
                        },
                        memory_meta={
                            **memory_meta,
                            "state": memory_store.get_state(conversation_id),
                        },
                        answer=answer,
                    )
                    self._save_turn(conversation_id, original_question, answer)
                    return {**state, "final_state": final_state}

        if renewal_slot_context and not has_date_in_text(question):
            year_month = (
                parse_year_month_from_text(original_question)
                or parse_year_month_from_text(question)
            )
            if year_month and conversation_id:
                year, month = year_month
                memory_store.update_state(
                    conversation_id,
                    {
                        "pending_contract_end_year": year,
                        "pending_contract_end_month": month,
                        "pending_field": "contract_end_day",
                    },
                )
                answer = build_contract_end_day_question(year, month)
                next_context_result = {
                    **context_result,
                    "response_mode": "ask_missing_info",
                    "required_missing_questions": [answer],
                    "partial_facts": {
                        "contract_end_year": year,
                        "contract_end_month": month,
                        "missing": ["contract_end_day"],
                    },
                }
                final_state = self._build_early_final_state(
                    question=question,
                    categories=categories,
                    context_result=next_context_result,
                    planner_result=planner_result,
                    intent_result=None,
                    scope_result=None,
                    missing_questions=[answer],
                    retrieval_quality={
                        "skipped": True,
                        "reason": "partial_contract_end_date",
                    },
                    memory_meta={
                        **memory_meta,
                        "state": memory_store.get_state(conversation_id),
                    },
                    answer=answer,
                )
                self._save_turn(conversation_id, original_question, answer)
                return {
                    **state,
                    "context_result": next_context_result,
                    "final_state": final_state,
                }

        required_missing_questions = context_result.get("required_missing_questions", [])
        if planner_validation.get("context_should_stop"):
            required_missing_questions = planner_validation.get(
                "context_missing_questions",
                required_missing_questions,
            )
            answer = "\n".join(str(question) for question in required_missing_questions)
            final_state = self._build_early_final_state(
                question=question,
                categories=categories,
                context_result=context_result,
                planner_result=planner_result,
                intent_result=None,
                scope_result=None,
                missing_questions=required_missing_questions,
                retrieval_quality={
                    "skipped": True,
                    "reason": "required_missing_information",
                },
                memory_meta=memory_meta,
                answer=answer,
                planner_validation=planner_validation,
            )
            self._save_turn(conversation_id, original_question, answer)
            return {**state, "final_state": final_state}

        planner_missing_questions = planner_validation.get("planner_missing_questions", [])
        if planner_validation.get("planner_should_stop"):
            answer = "\n".join(planner_missing_questions)
            final_state = self._build_early_final_state(
                question=question,
                categories=categories,
                context_result=context_result,
                planner_result=planner_result,
                intent_result=None,
                scope_result=None,
                missing_questions=planner_missing_questions,
                retrieval_quality={
                    "skipped": True,
                    "reason": "planner_required_missing_information",
                },
                memory_meta=memory_meta,
                answer=answer,
                planner_validation=planner_validation,
            )
            self._save_turn(conversation_id, original_question, answer)
            return {**state, "final_state": final_state}

        scope_result: dict[str, Any] | None = None
        if should_call_scope_analyzer(question=question, categories=categories):
            scope_result = analyze_b_part_scope(question)
            scope = scope_result.get("scope")
            if scope in {"out_of_scope", "ambiguous"}:
                answer = build_scope_guidance_answer(scope_result)
                final_state = self._build_early_final_state(
                    question=question,
                    categories=scope_result.get("suggested_categories", []),
                    context_result=context_result,
                    planner_result=planner_result,
                    intent_result=None,
                    scope_result=scope_result,
                    missing_questions=[scope_result.get("clarification_question", "")],
                    retrieval_quality={
                        "is_out_of_scope": scope == "out_of_scope",
                        "is_ambiguous_scope": scope == "ambiguous",
                        "reason": scope_result.get("reason"),
                    },
                    memory_meta=memory_meta,
                    answer=answer,
                )
                self._save_turn(conversation_id, original_question, answer)
                return {**state, "final_state": final_state}

            categories = merge_categories(
                categories,
                scope_result.get("suggested_categories", []),
            )

        return {
            **state,
            "question": question,
            "categories": categories,
            "context_result": context_result,
            "memory_meta": memory_meta,
            "scope_result": scope_result,
        }

    def _route_after_missing_scope(self, state: BPartGraphState) -> str:
        """missing/scope 노드 이후 다음 경로를 결정합니다."""
        if state.get("final_state"):
            return "end"
        return "continue"

    async def _retrieve_node(self, state: BPartGraphState) -> BPartGraphState:
        """LangGraph 노드: PGVector 검색과 검색 품질 보정을 수행합니다."""
        request = state.get("request", {})
        question = state["question"]
        categories = state.get("categories", [])
        intent_result = state.get("intent_result")
        top_k = int(request.get("top_k", 5))
        planner_validation = state.get("planner_validation", {})
        tools_to_use = planner_validation.get("tools_to_use", ["retriever"])
        if not isinstance(tools_to_use, list):
            tools_to_use = ["retriever"]
        executed_tools = list(state.get("executed_tools", []))
        skipped_tools = list(state.get("skipped_tools", []))

        rule_results = state.get("rule_results", [])
        calendar_events = state.get("calendar_events", [])
        pending_action = state.get("pending_action")

        if "retriever" not in tools_to_use:
            skipped_tools.append("retriever")
            return {
                **state,
                "top_k": top_k,
                "retrieved": [],
                "retrieval_quality": {
                    "skipped": True,
                    "reason": "retriever_not_requested_by_tool_policy",
                    "refined_by_llm": False,
                },
                "executed_tools": list(dict.fromkeys(executed_tools)),
                "skipped_tools": list(dict.fromkeys(skipped_tools)),
            }

        retrieved = self._retrieve(question=question, categories=categories, top_k=top_k)
        executed_tools.append("retriever")
        retrieval_quality = evaluate_retrieval_quality(retrieved)

        if should_refine_intent_after_retrieval(
            retrieval_quality=retrieval_quality,
            intent_result=intent_result,
        ):
            intent_result = analyze_b_part_intent(question)
            intent_result["trigger"] = "weak_retrieval"
            categories = merge_categories(
                categories,
                intent_result.get("categories", []),
            )
            rule_results = run_b_part_rules(question=question, categories=categories)
            calendar_events = build_calendar_event_candidates(rule_results)
            pending_action = build_calendar_pending_action(calendar_events)
            retrieved = self._retrieve(question=question, categories=categories, top_k=top_k)
            retrieval_quality = evaluate_retrieval_quality(retrieved)
            retrieval_quality["refined_by_llm"] = True
            if "rule_engine" not in executed_tools:
                executed_tools.append("rule_engine")
            if "retriever" not in executed_tools:
                executed_tools.append("retriever")
        else:
            retrieval_quality["refined_by_llm"] = False

        return {
            **state,
            "categories": categories,
            "intent_result": intent_result,
            "rule_results": rule_results,
            "calendar_events": calendar_events,
            "pending_action": pending_action,
            "top_k": top_k,
            "retrieved": retrieved,
            "retrieval_quality": retrieval_quality,
            "executed_tools": list(dict.fromkeys(executed_tools)),
            "skipped_tools": list(dict.fromkeys(skipped_tools)),
        }

    async def _answer_node(self, state: BPartGraphState) -> BPartGraphState:
        """LangGraph 노드: 검색/계산 결과를 바탕으로 최종 답변을 생성합니다."""
        final_state = await self._generate_final_answer(state)
        return {"final_state": final_state}

    async def _generate_final_answer(self, state: BPartGraphState) -> dict[str, Any]:
        """GPT 답변 생성, 캘린더 후보 문구 추가, 대화 저장을 수행합니다."""
        original_question = state["original_question"]
        conversation_id = state.get("conversation_id")
        question = state["question"]
        context_result = state["context_result"]
        memory_meta = state["memory_meta"]
        categories = state.get("categories", [])
        planner_result = state["planner_result"]
        planner_validation = state.get("planner_validation", {})
        intent_result = state.get("intent_result")
        rule_results = state.get("rule_results", [])
        calendar_events = state.get("calendar_events", [])
        pending_action = state.get("pending_action")
        retrieved = state.get("retrieved", [])
        retrieval_quality = state.get("retrieval_quality", {})
        scope_result = state.get("scope_result")
        executed_tools = state.get("executed_tools", [])
        skipped_tools = state.get("skipped_tools", [])

        missing_questions = find_missing_questions(question, categories)

        answer = generate_b_part_answer(
            user_question=question,
            retrieved_documents=retrieved,
            categories=categories,
            missing_questions=missing_questions,
            rule_results=rule_results,
        )
        calendar_answer_section = format_calendar_events_for_answer(calendar_events)
        if calendar_answer_section:
            answer = f"{answer.rstrip()}\n\n{calendar_answer_section}"

        final_state = {
            "question": question,
            "categories": categories,
            "context_result": context_result,
            "planner_result": planner_result,
            "planner_validation": planner_validation,
            "intent_result": intent_result,
            "scope_result": scope_result,
            "rule_results": rule_results,
            "calendar_events": calendar_events,
            "pending_action": pending_action,
            "calendar_tool_result": state.get("calendar_tool_result"),
            "executed_tools": executed_tools,
            "skipped_tools": skipped_tools,
            "missing_questions": missing_questions,
            "retrieved": retrieved,
            "retrieval_quality": retrieval_quality,
            "memory": memory_meta,
            "final_answer": answer,
            "response_stream": stream_text(answer),
        }
        self._save_turn(conversation_id, original_question, answer)
        return final_state

    def _build_early_final_state(
        self,
        *,
        question: str,
        categories: list[str],
        context_result: dict[str, Any],
        planner_result: dict[str, Any] | None,
        intent_result: dict[str, Any] | None,
        scope_result: dict[str, Any] | None,
        missing_questions: list[Any],
        retrieval_quality: dict[str, Any],
        memory_meta: dict[str, Any],
        answer: str,
        planner_validation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """조기 종료 노드에서 공통으로 사용하는 final_state를 만듭니다."""
        return {
            "question": question,
            "categories": categories,
            "context_result": context_result,
            "planner_result": planner_result,
            "planner_validation": planner_validation or {},
            "intent_result": intent_result,
            "scope_result": scope_result,
            "rule_results": [],
            "calendar_events": [],
            "pending_action": None,
            "calendar_registration": None,
            "calendar_tool_result": None,
            "executed_tools": [],
            "skipped_tools": ["rule_engine", "calendar_candidate", "retriever"],
            "missing_questions": missing_questions,
            "retrieved": [],
            "retrieval_quality": retrieval_quality,
            "memory": memory_meta,
            "final_answer": answer,
            "response_stream": stream_text(answer),
        }

    def _save_turn(
        self,
        conversation_id: str | None,
        user_question: str,
        assistant_answer: str,
    ) -> None:
        """conversation_id가 있을 때만 현재 턴을 InMemory에 저장합니다."""
        if not conversation_id:
            return
        memory_store.add_message(conversation_id, "user", user_question)
        memory_store.add_message(conversation_id, "assistant", assistant_answer)

    def _retrieve(self, question: str, categories: list[str], top_k: int) -> list[dict[str, Any]]:
        """
        B파트 검색 전략.

        기존 방식은 source_type 구분 없이 similarity 순으로만 검색했기 때문에
        관련성이 낮은 판례가 법령보다 먼저 들어오는 문제가 있었습니다.

        개선 방식:
        1. 예측 카테고리별로 법령(law)을 먼저 검색합니다.
        2. 판례(precedent)는 보조 근거로 적게 검색합니다.
        3. 중복을 제거합니다.
        4. 최종 결과는 법령을 먼저 배치하고, 판례는 뒤에 배치합니다.
        """
        if not categories:
            return [
                result.to_dict()
                for result in self.retriever.search_sync(query=question, top_k=top_k)
            ]

        law_results: list[dict[str, Any]] = []
        precedent_results: list[dict[str, Any]] = []

        search_categories = categories[:4]

        for category in search_categories:
            laws = self.retriever.search_sync(
                query=question,
                top_k=2,
                category=category,
                source_type="law",
            )
            law_results.extend(result.to_dict() for result in laws)

            for law_keyword, article in CORE_LAW_ANCHORS.get(category, []):
                anchor_query = f"{question}\n핵심 근거: {law_keyword} 제{article}조"
                anchor_candidates = self.retriever.search_sync(
                    query=anchor_query,
                    top_k=8,
                    category=category,
                    source_type="law",
                )
                for candidate in anchor_candidates:
                    candidate_dict = candidate.to_dict()
                    if is_core_law_anchor(candidate_dict, law_keyword, article):
                        candidate_dict.setdefault("metadata", {})[
                            "retrieval_reason"
                        ] = "core_law_anchor"
                        law_results.append(candidate_dict)
                        break

        for category in search_categories:
            precedents = self.retriever.search_sync(
                query=question,
                top_k=1,
                category=category,
                source_type="precedent",
            )
            precedent_results.extend(result.to_dict() for result in precedents)

        law_results = deduplicate_results(law_results)
        precedent_results = filter_precedents_by_similarity(
            deduplicate_results(precedent_results)
        )

        law_results.sort(key=lambda item: item.get("similarity", 0), reverse=True)
        precedent_results.sort(key=lambda item: item.get("similarity", 0), reverse=True)

        combined_results = law_results + precedent_results

        if not combined_results:
            combined_results = [
                result.to_dict()
                for result in self.retriever.search_sync(query=question, top_k=top_k)
            ]

        return combined_results[:top_k]

graph = BPartMVPGraph()
