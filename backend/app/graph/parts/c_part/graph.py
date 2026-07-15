"""
【LangGraph】C파트 답변 생성 그래프 - B단계: 병렬화

"""

import logging
from functools import partial
from typing import TypedDict, Optional
from datetime import datetime

from langgraph.graph import StateGraph, START, END
from langchain_core.language_models import BaseLanguageModel

from app.graph.parts.c_part.agents.answer_generator import (
    AnswerGeneratorAgent,
    extract_deposit_amount,
)

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════════
# 【State】
# ════════════════════════════════════════════════════════════════════════════════

class CPartState(TypedDict):
    """
    【그래프 State】

    """

    # 【입력】
    question: str
    search_results: dict               # {"statutes": [...], "precedents": [...]}
    chat_history: Optional[list]
    user_id: Optional[int]

    # 【Classifier가 채움】
    classifier_result: Optional[dict]
    deposit_amount: Optional[int]      # 보증금 액수 (비용 계산용)

    # 【각 노드가 채우는 섹션】
    situation_section: Optional[dict]
    legal_basis_section: Optional[dict]
    precedents_section: Optional[dict]
    action_steps_section: Optional[dict]
    expected_cost_section: Optional[dict]
    anticipated_disputes_section: Optional[dict]
    follow_up_questions: Optional[list[str]]

    # 【최종】
    answer: Optional[dict]
    error: Optional[str]


# ════════════════════════════════════════════════════════════════════════════════
# 【Node 0】Classifier + 보증금 추출  — 순차
# ════════════════════════════════════════════════════════════════════════════════

async def node_topic_classifier(
    state: CPartState,
    agent: AnswerGeneratorAgent,
) -> dict:

    try:
        # 【1】보증금 추출 (GPT 안 씀)
        deposit = extract_deposit_amount(
            question=state["question"],
            chat_history=state.get("chat_history"),
        )

        if deposit:
            logger.info(f"[Classifier] 보증금 추출: {deposit:,}원")
        else:
            logger.info("[Classifier] 보증금 액수 없음 → 비용 계산 생략")

        # 【2】카테고리3 범위인지 판단
        result = await agent.classify_topic(question=state["question"])

        # 【Off-topic】7단계를 건너뛰고 즉시 종료
        # → GPT 호출 8회 → 1회. 비용 8배 절감.
        if not result["is_relevant"]:
            logger.info(f"[Classifier] Off-topic: {result['reason']}")

            return {
                "classifier_result": result,
                "deposit_amount": deposit,
                "answer": {
                    "is_off_topic": True,
                    "message": (
                        "죄송해요, 이 챗봇은 주택임대차 보증금 반환·경매·배당 "
                        "관련 질문을 도와드립니다.\n\n"
                        "이런 질문을 해주세요:\n"
                        "• 보증금을 못 받았을 때 어떻게 하나요?\n"
                        "• 임차권등기명령은 어떻게 신청하나요?\n"
                        "• 경매가 나갔는데 보증금을 받을 수 있나요?\n"
                        "• 소액보증금 최우선변제가 뭔가요?"
                    ),
                    "confidence_score": result["confidence"],
                    "generated_at": datetime.now().isoformat(),
                },
            }

        # 【정상】다음 단계로
        return {
            "classifier_result": result,
            "deposit_amount": deposit,
        }

    except Exception as e:
        logger.error(f"[Classifier] 실패: {e}")
        return {"error": f"[Classifier] 실패: {e}"}


# ════════════════════════════════════════════════════════════════════════════════
# 【Node 1】상황 진단  — 순차 (모든 노드의 전제)
# ════════════════════════════════════════════════════════════════════════════════

async def node_situation_generator(
    state: CPartState,
    agent: AnswerGeneratorAgent,
) -> dict:
    """
    【Node 1】상황 진단

    ⚠️ 이 노드는 병렬화할 수 없습니다.
       뒤의 모든 노드가 situation 결과를 프롬프트에 넣기 때문입니다.
       진짜 의존관계라서 순차로 둡니다.
    """
    try:
        section = await agent.generate_situation(
            question=state["question"],
            statutes=state["search_results"].get("statutes", []),
            precedents=state["search_results"].get("precedents", []),
            chat_history=state.get("chat_history"),
        )
        return {"situation_section": section}

    except Exception as e:
        logger.error(f"[Node 1] 상황 진단 실패: {e}")
        return {"error": f"[Node 1] 상황 진단 실패: {e}"}


# ════════════════════════════════════════════════════════════════════════════════
# 【Node 2·3】법 조문 / 판례  — ⚡ 병렬 실행
# ════════════════════════════════════════════════════════════════════════════════
# 이 두 노드는 동시에 실행됩니다.
#
# 병렬화 근거: 서로의 결과를 참조하지 않습니다.
#   - legal_basis는 조문(statutes) + situation만 봄
#   - precedents는 판례(precedents) + situation만 봄
#
# 순차: legal_basis(20초) → precedents(15초) = 35초
# 병렬: max(20초, 15초)                      = 20초
# → 15초 절약

async def node_legal_basis_generator(
    state: CPartState,
    agent: AnswerGeneratorAgent,
) -> dict:
    """
    【Node 2】법 조문  ⚡ 병렬

    ⚠️ 반드시 자기 필드만 반환하세요!
       precedents 노드와 동시에 실행되므로,
       state 전체를 반환하면 두 노드의 반환값이 충돌합니다.
    """
    try:
        situation = state.get("situation_section") or {}

        section = await agent.generate_legal_basis(
            question=state["question"],
            statutes=state["search_results"].get("statutes", []),
            situation_content=situation.get("content", ""),
        )
        return {"legal_basis_section": section}   # ← 자기 필드만!

    except Exception as e:
        logger.error(f"[Node 2] 법 조문 실패: {e}")
        return {"error": f"[Node 2] 법 조문 실패: {e}"}


async def node_precedents_generator(
    state: CPartState,
    agent: AnswerGeneratorAgent,
) -> dict:
    """【Node 3】판례  ⚡ 병렬 (legal_basis와 동시 실행)"""
    try:
        situation = state.get("situation_section") or {}

        section = await agent.generate_precedents(
            question=state["question"],
            precedents=state["search_results"].get("precedents", []),
            situation_content=situation.get("content", ""),
        )
        return {"precedents_section": section}   # ← 자기 필드만!

    except Exception as e:
        logger.error(f"[Node 3] 판례 실패: {e}")
        return {"error": f"[Node 3] 판례 실패: {e}"}


# ════════════════════════════════════════════════════════════════════════════════
# 【Node 4】행동 절차  — 순차 (합류 지점)
# ════════════════════════════════════════════════════════════════════════════════

async def node_action_steps_generator(
    state: CPartState,
    agent: AnswerGeneratorAgent,
) -> dict:

    try:
        situation = state.get("situation_section") or {}
        legal_basis = state.get("legal_basis_section") or {}

        section = await agent.generate_action_steps(
            question=state["question"],
            situation_content=situation.get("content", ""),
            legal_basis_content=legal_basis.get("content", ""),
        )
        return {"action_steps_section": section}

    except Exception as e:
        logger.error(f"[Node 4] 행동 절차 실패: {e}")
        return {"error": f"[Node 4] 행동 절차 실패: {e}"}


# ════════════════════════════════════════════════════════════════════════════════
# 【Node 5·6·7】비용 / 반박 / FAQ  — ⚡⚡⚡ 3개 병렬 실행
# ════════════════════════════════════════════════════════════════════════════════


async def node_expected_cost_generator(
    state: CPartState,
    agent: AnswerGeneratorAgent,
) -> dict:

    try:
        action_steps = state.get("action_steps_section") or {}

        section = await agent.generate_expected_cost(
            question=state["question"],
            action_steps_content=action_steps.get("content", ""),
            deposit_amount=state.get("deposit_amount"),
        )
        return {"expected_cost_section": section}

    except Exception as e:
        logger.error(f"[Node 5] 예상 비용 실패: {e}")
        return {"error": f"[Node 5] 예상 비용 실패: {e}"}


async def node_anticipated_disputes_generator(
    state: CPartState,
    agent: AnswerGeneratorAgent,
) -> dict:
    """【Node 6】임대인 반박 & 대응  ⚡ 병렬"""
    try:
        situation = state.get("situation_section") or {}
        legal_basis = state.get("legal_basis_section") or {}
        precedents = state.get("precedents_section") or {}

        section = await agent.generate_anticipated_disputes(
            question=state["question"],
            situation_content=situation.get("content", ""),
            legal_basis_content=legal_basis.get("content", ""),
            precedents_content=precedents.get("content", ""),
        )
        return {"anticipated_disputes_section": section}

    except Exception as e:
        logger.error(f"[Node 6] 반박 대응 실패: {e}")
        return {"error": f"[Node 6] 반박 대응 실패: {e}"}


async def node_follow_up_questions_generator(
    state: CPartState,
    agent: AnswerGeneratorAgent,
) -> dict:
    """【Node 7】FAQ  ⚡ 병렬"""
    try:
        situation = state.get("situation_section") or {}
        action_steps = state.get("action_steps_section") or {}

        faqs = await agent.generate_follow_up_questions(
            question=state["question"],
            situation_content=situation.get("content", ""),
            action_steps_content=action_steps.get("content", ""),
        )
        return {"follow_up_questions": faqs}

    except Exception as e:
        logger.error(f"[Node 7] FAQ 실패: {e}")
        return {"error": f"[Node 7] FAQ 실패: {e}"}


# ════════════════════════════════════════════════════════════════════════════════
# 【Node 8】최종 조립  — 순차 (합류 지점)
# ════════════════════════════════════════════════════════════════════════════════

async def node_answer_assembler(
    state: CPartState,
    agent: AnswerGeneratorAgent,
) -> dict:
    """
    【Node 8】최종 조립

    ⚠️ cost / disputes / faq 3개가 "전부" 끝나야 실행됩니다.
       LangGraph가 알아서 기다립니다.

    ⚠️ GPT 호출이 없습니다 (조립 + 신뢰도 계산만).
       그래서 시간이 거의 0초입니다.
    """
    try:
        answer = agent.assemble_answer(
            question=state["question"],
            situation=state.get("situation_section") or {},
            legal_basis=state.get("legal_basis_section") or {},
            precedents=state.get("precedents_section") or {},
            action_steps=state.get("action_steps_section") or {},
            expected_cost=state.get("expected_cost_section") or {},
            anticipated_disputes=state.get("anticipated_disputes_section") or {},
            follow_up_questions=state.get("follow_up_questions") or [],
            search_results=state["search_results"],
            deposit_amount=state.get("deposit_amount"),
        )
        return {"answer": answer}

    except Exception as e:
        logger.error(f"[Node 8] 조립 실패: {e}")
        return {"error": f"[Node 8] 조립 실패: {e}"}


# ════════════════════════════════════════════════════════════════════════════════
# 【그래프 빌드】
# ════════════════════════════════════════════════════════════════════════════════

def build_c_part_graph(llm: BaseLanguageModel):
    """
    【빌드】C파트 답변 생성 그래프 (병렬화 버전)

    """
    agent = AnswerGeneratorAgent(llm)
    graph = StateGraph(CPartState)

    # ────────────────────────────────────────────────────────────────────
    # 【노드 등록】
    # ────────────────────────────────────────────────────────────────────

    logger.info("[Graph] 노드 등록")

    graph.add_node("classifier", partial(node_topic_classifier, agent=agent))
    graph.add_node("situation", partial(node_situation_generator, agent=agent))
    graph.add_node("legal_basis", partial(node_legal_basis_generator, agent=agent))
    graph.add_node("precedents", partial(node_precedents_generator, agent=agent))
    graph.add_node("action_steps", partial(node_action_steps_generator, agent=agent))
    graph.add_node("expected_cost", partial(node_expected_cost_generator, agent=agent))
    graph.add_node("anticipated_disputes", partial(node_anticipated_disputes_generator, agent=agent))
    graph.add_node("follow_up_questions", partial(node_follow_up_questions_generator, agent=agent))
    graph.add_node("assemble", partial(node_answer_assembler, agent=agent))

    # ────────────────────────────────────────────────────────────────────
    # 【엣지 연결】⚡ 병렬 구조
    # ────────────────────────────────────────────────────────────────────

    logger.info("[Graph] 엣지 연결 (병렬 구조)")

    # 【시작】
    graph.add_edge(START, "classifier")

    # 【분기】off-topic이면 즉시 종료
    def route_after_classification(state: CPartState) -> str:
        """
        Classifier 결과에 따라 목적지 결정.
        반환값은 아래 매핑 dict의 '키'와 일치해야 합니다.
        """
        classifier = state.get("classifier_result") or {}
        return "continue" if classifier.get("is_relevant", False) else "stop"

    graph.add_conditional_edges(
        "classifier",
        route_after_classification,
        {
            "continue": "situation",   # 키 → 노드명 (문자열)
            "stop": END,               # 키 → END 상수 (따옴표 X!)
        },
    )

    # ────────────────────────────────────────────────────────────────────
    # 【⚡ 병렬 그룹 1】situation → (legal_basis ∥ precedents)
    # ────────────────────────────────────────────────────────────────────

    graph.add_edge("situation", "legal_basis")
    graph.add_edge("situation", "precedents")

    # ────────────────────────────────────────────────────────────────────
    # 【합류 1】(legal_basis + precedents) → action_steps
    # ────────────────────────────────────────────────────────────────────

    graph.add_edge("legal_basis", "action_steps")
    graph.add_edge("precedents", "action_steps")

    # ────────────────────────────────────────────────────────────────────
    # 【⚡ 병렬 그룹 2】action_steps → (cost ∥ disputes ∥ faq)
    # ────────────────────────────────────────────────────────────────────

    graph.add_edge("action_steps", "expected_cost")
    graph.add_edge("action_steps", "anticipated_disputes")
    graph.add_edge("action_steps", "follow_up_questions")

    # ────────────────────────────────────────────────────────────────────
    # 【합류 2】(cost + disputes + faq) → assemble
    # ────────────────────────────────────────────────────────────────────

    graph.add_edge("expected_cost", "assemble")
    graph.add_edge("anticipated_disputes", "assemble")
    graph.add_edge("follow_up_questions", "assemble")

    # 【종료】
    graph.add_edge("assemble", END)

    logger.info("[Graph] 컴파일")
    compiled = graph.compile()
    logger.info("[Graph] 준비 완료 (병렬 구조)")

    return compiled