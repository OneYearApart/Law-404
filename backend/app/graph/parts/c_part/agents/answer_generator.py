"""
【AnswerGeneratorAgent】C파트 답변 생성 - Phase 3 수정판
"""

import re
import logging
from typing import Optional
from datetime import datetime

from langchain_core.language_models import BaseLanguageModel

from app.llm.c_part.prompts import (
    format_topic_classifier_prompt,
    format_situation_prompt,
    format_legal_basis_prompt,
    format_precedents_prompt,
    format_action_steps_prompt,
    format_expected_cost_prompt,
    format_anticipated_disputes_prompt,
    format_follow_up_questions_prompt,
)
from app.rag.repositories.cost_repository import CostRepository

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════════
# 【헬퍼 1】검색 결과 → 프롬프트 컨텍스트 변환
# ════════════════════════════════════════════════════════════════════════════════

def format_statutes_context(statutes: list[dict]) -> str:
    """
    【포맷팅】조문 리스트 → 프롬프트 텍스트

    입력: [{"article_number": "8조", "title": "...", "content": "..."}, ...]
    """
    if not statutes:
        return "(검색된 조문 없음)"

    parts = []
    for s in statutes:
        num = s.get("article_number", "")
        title = s.get("title", "")
        content = s.get("content", "")
        parts.append(f"【제{num} - {title}】\n{content}")

    return "\n\n".join(parts)


def format_precedents_context(precedents: list[dict]) -> str:
    """
    【포맷팅】판례 리스트 → 프롬프트 텍스트

    """
    if not precedents:
        return "(검색된 판례 없음)"

    # 【법원 코드 → 이름】
    COURT_NAMES = {0: "대법원", 1: "고등법원", 2: "지방법원"}

    parts = []
    for p in precedents:
        case_number = p.get("case_number", "")
        case_name = p.get("case_name", "")
        content = p.get("content", "")

        # 【헤더 조립】있는 정보만 씁니다
        header_bits = [case_number] if case_number else []

        court_level = p.get("court_level")
        if court_level is not None and court_level in COURT_NAMES:
            header_bits.append(COURT_NAMES[court_level])

        case_year = p.get("case_year")
        if case_year:
            header_bits.append(str(case_year))

        header = " - ".join(header_bits) if header_bits else "판례"

        block = f"【{header}】"
        if case_name:
            block += f"\n사건명: {case_name}"

        # 【판결 결과】있으면 표시 (임차인 승소/패소)
        ruling = p.get("ruling_type")
        if ruling:
            block += f"\n판결: {ruling}"

        block += f"\n{content}"
        parts.append(block)

    return "\n\n".join(parts)


# ════════════════════════════════════════════════════════════════════════════════
# 【헬퍼 2】보증금 액수 추출  ← 신규
# ════════════════════════════════════════════════════════════════════════════════

def extract_deposit_amount(question: str, chat_history: Optional[list] = None) -> Optional[int]:
    """
    【추출】질문에서 보증금 액수를 찾습니다.
    """
    # 【검색 대상】질문 + 대화 히스토리
    text = question
    if chat_history:
        for msg in chat_history:
            if isinstance(msg, dict) and msg.get("role") == "user":
                text += " " + msg.get("content", "")

    # ────────────────────────────────────────────────────────────────────
    # 【패턴 1】"1억 5천만원", "2억" 같은 억 단위
    # ────────────────────────────────────────────────────────────────────
    m = re.search(r"(\d+)\s*억\s*(?:(\d+)\s*천)?\s*(?:(\d+)\s*백)?", text)
    if m:
        amount = int(m.group(1)) * 100_000_000
        if m.group(2):  # "5천"
            amount += int(m.group(2)) * 10_000_000
        if m.group(3):  # "5백"
            amount += int(m.group(3)) * 1_000_000
        return amount

    # ────────────────────────────────────────────────────────────────────
    # 【패턴 2】"5천만원", "3천5백만원"
    # ────────────────────────────────────────────────────────────────────
    m = re.search(r"(\d+)\s*천\s*(?:(\d+)\s*백)?\s*만\s*원", text)
    if m:
        amount = int(m.group(1)) * 10_000_000
        if m.group(2):
            amount += int(m.group(2)) * 1_000_000
        return amount

    # ────────────────────────────────────────────────────────────────────
    # 【패턴 3】"5000만원", "3,000만원"
    # ────────────────────────────────────────────────────────────────────
    m = re.search(r"([\d,]+)\s*만\s*원", text)
    if m:
        num = int(m.group(1).replace(",", ""))
        return num * 10_000

    # ────────────────────────────────────────────────────────────────────
    # 【패턴 4】"50,000,000원" (원 단위 직접 표기)
    # ────────────────────────────────────────────────────────────────────
    m = re.search(r"([\d,]{7,})\s*원", text)
    if m:
        return int(m.group(1).replace(",", ""))

    # 【못 찾음】추측하지 않고 None
    return None


# ════════════════════════════════════════════════════════════════════════════════
# 【헬퍼 3】인용문 추출
# ════════════════════════════════════════════════════════════════════════════════

def extract_citations(text: str) -> list[str]:
    """
    【추출】생성된 텍스트에서 조문·판례 인용 찾기

    용도: 답변에 근거가 몇 개 인용됐는지 세기 (품질 지표)
    """
    citations = []

    # 【조문】"제8조", "제3조의2"
    for m in re.finditer(r"제\s*(\d+조(?:의\d+)?)", text):
        c = f"제{m.group(1)}"
        if c not in citations:
            citations.append(c)

    # 【판례】"2023다202228"
    for m in re.finditer(r"(\d{4}[가-힣]\d+)", text):
        c = m.group(1)
        if c not in citations:
            citations.append(c)

    return citations


# ════════════════════════════════════════════════════════════════════════════════
# 【헬퍼 4】금지 표현 검증  ← 강화
# ════════════════════════════════════════════════════════════════════════════════

def validate_forbidden_phrases(
    text: str,
    allow_amounts: bool = False,
) -> tuple[bool, list[str]]:

    violations = []

    # 【공통 금지】모든 섹션에서 금지
    patterns = [
        (r"성공률", "성공률 언급"),
        (r"승소\s*(?:확률|가능성)\s*\d+\s*%", "승소 확률 수치"),
        (r"난이도", "난이도 언급"),
        (r"\d+\s*%\s*(?:정도|가량)?\s*(?:성공|승소|이길)", "임의의 확률"),
        (r"대부분\s*(?:이기|승소|성공)", "근거 없는 단정"),
        (r"평균\s*\d+\s*(?:개월|주|일)", "임의의 평균 기간"),
    ]

    # 【금액 금지】allow_amounts=False일 때만
    # → action_steps 등에서 금액을 지어내는 것을 막습니다
    if not allow_amounts:
        patterns.extend([
            (r"약\s*[\d,]+\s*원", "임의의 금액"),
            (r"[\d,]+\s*[~-]\s*[\d,]+\s*원", "임의의 금액 범위"),
            (r"[\d,]+\s*만\s*원\s*(?:정도|가량|내외)", "임의의 금액"),
        ])

    for pattern, label in patterns:
        for m in re.finditer(pattern, text):
            violations.append(f"{label}: '{m.group()}'")

    return len(violations) == 0, violations


# ════════════════════════════════════════════════════════════════════════════════
# 【AnswerGeneratorAgent】
# ════════════════════════════════════════════════════════════════════════════════

class AnswerGeneratorAgent:
    """
    【C파트 답변 생성 Agent】
    """

    def __init__(
        self,
        llm: BaseLanguageModel,
        cost_repo: Optional[CostRepository] = None,
    ):
        """
        Args:
            llm: ChatOpenAI 인스턴스
            cost_repo: 비용 조회 레포지토리. 없으면 새로 만듦.
                       (테스트에서 Mock을 주입할 수 있게 파라미터로 뺐습니다)
        """
        self.llm = llm
        self.cost_repo = cost_repo or CostRepository()

    # ────────────────────────────────────────────────────────────────────────
    # 【Node 0】Topic Classifier
    # ────────────────────────────────────────────────────────────────────────

    async def classify_topic(self, question: str) -> dict:
        """
        【분류】질문을 3가지로 분류 (Supervisor 역할)

        Returns:
            {
              "is_relevant": bool,      # 기존 코드 호환용 off-topic 분기 사용을 위한 로직
              "intent": str,            # "consultation" | "document" | "irrelevant"
              "confidence": float,
              "reason": str,
            }
        """
        prompt = format_topic_classifier_prompt(question)
        response = await self.llm.ainvoke(prompt)
        content = response.content.strip().upper()

        # 【의도 파싱】
        if "DOCUMENT" in content:
            intent = "document"
            is_relevant = True
        elif "CONSULTATION" in content:
            intent = "consultation"
            is_relevant = True
        elif "IRRELEVANT" in content:
            intent = "irrelevant"
            is_relevant = False
        else:
            intent = "consultation"
            is_relevant = True

        # 【신뢰도
        matched = any(
            kw in content
            for kw in ["DOCUMENT", "CONSULTATION", "IRRELEVANT"]
        )

        reason_map = {
            "consultation": "카테고리3 상담 (보증금·경매·배당)",
            "document": "문서 작성 요청 (내용증명 등)",
            "irrelevant": "카테고리3 범위 외 질문",
        }

        return {
            "is_relevant": is_relevant,
            "intent": intent,
            "confidence": 0.95 if matched else 0.6,
            "reason": reason_map[intent],
        }
    # ────────────────────────────────────────────────────────────────────────
    # 【Node 1】상황 진단
    # ────────────────────────────────────────────────────────────────────────

    async def generate_situation(
        self,
        question: str,
        statutes: list[dict],
        precedents: list[dict],
        chat_history: Optional[list] = None,
    ) -> dict:
        """
        【Node 1】상황 진단

        ⚠️ Phase 3 수정: 프롬프트에서 조문 인용을 의무화했습니다.
           기존에는 citations_count가 0이었습니다.
        """
        logger.info("[Node 1] 상황 진단 생성")

        prompt = format_situation_prompt(
            question=question,
            statutes_context=format_statutes_context(statutes),
            precedents_context=format_precedents_context(precedents),
        )

        response = await self.llm.ainvoke(prompt)
        content = response.content

        # 【검증】금액 금지 (상황 진단에 금액이 나오면 안 됨)
        is_safe, violations = validate_forbidden_phrases(content, allow_amounts=False)
        if not is_safe:
            logger.warning(f"[Node 1] 금지 표현: {violations}")

        return {
            "title": "상황 진단",
            "content": content,
            "citations": extract_citations(content),
        }

    # ────────────────────────────────────────────────────────────────────────
    # 【Node 2】법 조문
    # ────────────────────────────────────────────────────────────────────────

    async def generate_legal_basis(
        self,
        question: str,
        statutes: list[dict],
        situation_content: str,
    ) -> dict:
        """【Node 2】법 조문 설명"""
        logger.info("[Node 2] 법 조문 생성")

        prompt = format_legal_basis_prompt(
            question=question,
            situation_content=situation_content,
            statutes_context=format_statutes_context(statutes),
        )

        response = await self.llm.ainvoke(prompt)
        content = response.content

        is_safe, violations = validate_forbidden_phrases(content, allow_amounts=False)
        if not is_safe:
            logger.warning(f"[Node 2] 금지 표현: {violations}")

        return {
            "title": "관련 법 조문",
            "content": content,
            "citations": extract_citations(content),
        }

    # ────────────────────────────────────────────────────────────────────────
    # 【Node 3】판례
    # ────────────────────────────────────────────────────────────────────────

    async def generate_precedents(
        self,
        question: str,
        precedents: list[dict],
        situation_content: str,
    ) -> dict:
        """
        【Node 3】판례 분석

        ⚠️ 검증 추가: GPT가 만들어낸 사건번호가 있는지 확인합니다.
        """
        logger.info("[Node 3] 판례 분석 생성")

        prompt = format_precedents_prompt(
            question=question,
            situation_content=situation_content,
            precedents_context=format_precedents_context(precedents),
        )

        response = await self.llm.ainvoke(prompt)
        content = response.content

        # 【검증 1】금지 표현
        is_safe, violations = validate_forbidden_phrases(content, allow_amounts=False)
        if not is_safe:
            logger.warning(f"[Node 3] 금지 표현: {violations}")

        # 【검증 2】사건번호 창작 여부  ← 중요!
        # 【After】병합사건 분해
        # DB의 "2022다246610, 246627"을 개별 번호로 쪼갭니다.
        # 뒤 번호(246627)는 "다"가 생략되어 있으므로 앞 번호의 연도+다를 붙여줍니다.
        real_cases = set()
        for p in precedents:
            raw = p.get("case_number", "")
            if not raw:
                continue
            # 정식 번호 추출 (2022다246610)
            for m in re.finditer(r"\d{4}[가-힣]\d+", raw):
                real_cases.add(m.group())
            # 병합된 뒷번호 (", 246627") → 앞 번호의 접두사 붙이기
            prefix_m = re.match(r"(\d{4}[가-힣])", raw)
            if prefix_m:
                prefix = prefix_m.group(1)
                for m in re.finditer(r",\s*(\d+)", raw):
                    real_cases.add(f"{prefix}{m.group(1)}")

        cited_cases = set(re.findall(r"\d{4}[가-힣]\d+", content))
        fabricated = cited_cases - real_cases

        if fabricated:
            logger.error(
                f"[Node 3] ⚠️ 존재하지 않는 판례를 인용했습니다: {fabricated}\n"
                f"   실제 검색된 판례: {real_cases}"
            )

        return {
            "title": "관련 판례",
            "content": content,
            "citations": extract_citations(content),
        }

    # ────────────────────────────────────────────────────────────────────────
    # 【Node 4】행동 절차  ← 비용 언급 금지
    # ────────────────────────────────────────────────────────────────────────

    async def generate_action_steps(
        self,
        question: str,
        situation_content: str,
        legal_basis_content: str,
    ) -> dict:
        """
        【Node 4】행동 절차

        ⚠️ Phase 3 핵심 수정:
           비용 언급을 금지했습니다.
           기존에는 action_steps와 expected_cost가 각자 금액을 지어내서
           같은 답변 안에서 임차권등기명령 비용이 달랐습니다.

           대신 절차별 '신청 자격'만 DB에서 가져와서 전달합니다.
        """
        logger.info("[Node 4] 행동 절차 생성")

        # 【DB 조회】절차별 신청 자격만 (비용은 안 넘김!)
        procedures = self.cost_repo.get_all_procedures()
        eligibility_lines = []
        for p in procedures:
            if p.get("eligibility"):
                eligibility_lines.append(
                    f"- {p['procedure_name']}: {p['eligibility']}"
                )
        procedure_eligibility = "\n".join(eligibility_lines) or "(절차 정보 없음)"

        prompt = format_action_steps_prompt(
            question=question,
            situation_content=situation_content,
            legal_basis_content=legal_basis_content,
            procedure_eligibility=procedure_eligibility,
        )

        response = await self.llm.ainvoke(prompt)
        content = response.content

        # 【검증】금액이 나오면 안 됨! (allow_amounts=False)
        is_safe, violations = validate_forbidden_phrases(content, allow_amounts=False)
        if not is_safe:
            logger.warning(
                f"[Node 4] ⚠️ 절차 섹션에 금액이 언급됐습니다: {violations}\n"
                f"   비용은 expected_cost 섹션에서만 다뤄야 합니다."
            )

        return {
            "title": "구체적 행동 절차",
            "content": content,
            "citations": extract_citations(content),
        }

    # ────────────────────────────────────────────────────────────────────────
    # 【Node 5】예상 비용  ← 가장 크게 바뀐 부분
    # ────────────────────────────────────────────────────────────────────────

    async def generate_expected_cost(
        self,
        question: str,
        action_steps_content: str,
        deposit_amount: Optional[int] = None,
    ) -> dict:
        """
        【Node 5】예상 비용

        ⚠️ Phase 3 핵심 수정:
           1) DB의 공식 비용 데이터를 프롬프트에 주입
           2) 보증금 액수를 알면 코드가 직접 계산해서 결과만 전달

        왜 코드가 계산하나?
           LLM은 산수를 못 합니다.
           "5천만원 × 45/10,000 + 5,000" 같은 계산을 시키면 틀립니다.
           → 파이썬이 계산하고, GPT는 설명만 합니다.

        Args:
            deposit_amount: 보증금 액수. None이면 계산하지 않고 안내만.
        """
        logger.info(f"[Node 5] 예상 비용 생성 (보증금: {deposit_amount})")

        # 【1】DB에서 공식 비용 데이터 가져오기
        official_costs = self.cost_repo.get_procedure_costs_for_prompt()

        # 【2】보증금을 알면 코드가 직접 계산
        calculated_costs = ""

        if deposit_amount:
            lines = [
                "【코드가 계산한 정확한 금액 - 이 숫자를 그대로 쓰세요】",
                f"기준 보증금(소가): {deposit_amount:,}원",
                "",
            ]

            for proc in ["임차권등기명령", "소액사건", "일반소송"]:
                result = self.cost_repo.calculate_total_cost(deposit_amount, proc)

                # 【소액사건 자격 체크】3천만원 초과면 대상 아님
                if proc == "소액사건" and deposit_amount > 30_000_000:
                    lines.append(
                        f"━ {proc}: ❌ 대상 아님 "
                        f"(소가 3,000만원 초과 — 일반소송으로 진행해야 함)"
                    )
                    lines.append("")
                    continue

                # 【일반소송 자격 체크】3천만원 이하면 소액사건이 유리
                if proc == "일반소송" and deposit_amount <= 30_000_000:
                    lines.append(
                        f"━ {proc}: 가능하지만 소액사건이 더 빠르고 저렴합니다"
                    )

                if result["total"]:
                    lines.append(f"━ {proc}: 총 {result['total']:,}원")
                    for b in result["breakdown"]:
                        lines.append(f"    · {b}")
                else:
                    lines.append(f"━ {proc}: 공식 금액 자료 없음")

                lines.append("")

            calculated_costs = "\n".join(lines)

        # 【3】프롬프트 조립
        prompt = format_expected_cost_prompt(
            question=question,
            action_steps_content=action_steps_content,
            official_costs=official_costs,
            calculated_costs=calculated_costs,
        )

        response = await self.llm.ainvoke(prompt)
        content = response.content

        # 【검증】여기서는 금액이 나와도 정상 (allow_amounts=True)
        #        단, 성공률·난이도는 여전히 금지
        is_safe, violations = validate_forbidden_phrases(content, allow_amounts=True)
        if not is_safe:
            logger.warning(f"[Node 5] 금지 표현: {violations}")

        return {
            "title": "예상 비용",
            "content": content,
            "citations": extract_citations(content),
        }

    # ────────────────────────────────────────────────────────────────────────
    # 【Node 6】반박 대응
    # ────────────────────────────────────────────────────────────────────────

    async def generate_anticipated_disputes(
        self,
        question: str,
        situation_content: str,
        legal_basis_content: str,
        precedents_content: str,
    ) -> dict:
        """【Node 6】임대인 반박 & 대응"""
        logger.info("[Node 6] 반박 대응 생성")

        prompt = format_anticipated_disputes_prompt(
            question=question,
            situation_content=situation_content,
            legal_basis_content=legal_basis_content,
            precedents_content=precedents_content,
        )

        response = await self.llm.ainvoke(prompt)
        content = response.content

        is_safe, violations = validate_forbidden_phrases(content, allow_amounts=False)
        if not is_safe:
            logger.warning(f"[Node 6] 금지 표현: {violations}")

        return {
            "title": "임대인 반박 & 대응",
            "content": content,
            "citations": extract_citations(content),
        }

    # ────────────────────────────────────────────────────────────────────────
    # 【Node 7】FAQ  ← 파싱 문제 해결
    # ────────────────────────────────────────────────────────────────────────

    async def generate_follow_up_questions(
        self,
        question: str,
        situation_content: str,
        action_steps_content: str,
    ) -> list[str]:
        """
        【Node 7】FAQ

        ⚠️ Phase 3 수정: 정규식을 관대하게 바꿨습니다.

        기존 문제:
          GPT가 매번 다른 형식으로 출력 → 정규식이 깨져서 5개가 1개로 파싱됨
            - "**Q2:** 질문"   (볼드)
            - "### Q1: 질문"    (헤더)
            - "Q1: 질문"        (정상)

        해결:
          1) 프롬프트에서 형식을 엄격히 강제 (prompts.py)
          2) 그래도 마크다운이 섞일 수 있으니 정규식도 관대하게 (여기)
        """
        logger.info("[Node 7] FAQ 생성")

        prompt = format_follow_up_questions_prompt(
            question=question,
            situation_content=situation_content,
            action_steps_content=action_steps_content,
        )

        response = await self.llm.ainvoke(prompt)
        content = response.content

        is_safe, violations = validate_forbidden_phrases(content, allow_amounts=False)
        if not is_safe:
            logger.warning(f"[Node 7] 금지 표현: {violations}")

        return self._parse_faq(content)

    @staticmethod
    def _parse_faq(content: str) -> list[str]:
        """
        【파싱】GPT 출력 → Q&A 리스트

        관대한 파싱:
        - 앞에 #, *, 공백이 붙어도 OK
        - Q1:, Q:, **Q1:** 전부 인식
        - A1:, A:, **A1:** 전부 인식
        """
        # 【1단계】마크다운 제거
        # ** 볼드, ### 헤더, --- 구분선을 걷어냅니다
        cleaned = content
        cleaned = re.sub(r"\*\*", "", cleaned)          # 볼드 제거
        cleaned = re.sub(r"^#+\s*", "", cleaned, flags=re.MULTILINE)  # 헤더 제거
        cleaned = re.sub(r"^\s*-{3,}\s*$", "", cleaned, flags=re.MULTILINE)  # 구분선 제거

        # 【2단계】Q/A 쌍 추출
        # Q로 시작 → A가 나올 때까지 = 질문
        # A로 시작 → 다음 Q가 나올 때까지 = 답변
        pattern = re.compile(
            r"Q\d*\s*[:：]\s*(?P<q>.+?)\s*\n+\s*A\d*\s*[:：]\s*(?P<a>.+?)"
            r"(?=\n\s*Q\d*\s*[:：]|\Z)",
            re.DOTALL,
        )

        faqs = []
        for m in pattern.finditer(cleaned):
            q = m.group("q").strip().strip('"').strip("'")
            a = m.group("a").strip()

            # 【정리】답변 내부의 여분 개행 정리
            a = re.sub(r"\n{2,}", "\n", a).strip()

            if q and a:
                faqs.append(f"Q: {q}\nA: {a}")

        # 【폴백】파싱이 완전히 실패하면
        if not faqs:
            logger.warning(
                "[Node 7] FAQ 파싱 실패 — 원문을 그대로 반환합니다.\n"
                f"원문 앞부분: {content[:120]}"
            )
            return [content.strip()]

        logger.info(f"[Node 7] FAQ {len(faqs)}개 파싱 완료")
        return faqs

    # ────────────────────────────────────────────────────────────────────────
    # 【Node 8】최종 조립
    # ────────────────────────────────────────────────────────────────────────

    def assemble_answer(
        self,
        question: str,
        situation: dict,
        legal_basis: dict,
        precedents: dict,
        action_steps: dict,
        expected_cost: dict,
        anticipated_disputes: dict,
        follow_up_questions: list[str],
        search_results: dict,
        deposit_amount: Optional[int] = None,
    ) -> dict:
        """【Node 8】최종 조립 + 신뢰도 계산"""
        logger.info("[Node 8] 최종 조립")

        confidence = self._calculate_confidence(search_results, deposit_amount)

        return {
            "situation": situation,
            "legal_basis": legal_basis,
            "precedents": precedents,
            "action_steps": action_steps,
            "expected_cost": expected_cost,
            "anticipated_disputes": anticipated_disputes,
            "follow_up_questions": follow_up_questions,
            "question": question,
            "generated_at": datetime.now().isoformat(),
            "confidence_score": confidence,
            "deposit_amount": deposit_amount,  # 계산에 쓴 금액 (투명성)
        }

    @staticmethod
    def _calculate_confidence(
        search_results: dict,
        deposit_amount: Optional[int] = None,
    ) -> float:
        """
        【계산】답변 신뢰도 (0.0 ~ 1.0)

        기준:
          기본값                0.3
          조문 3개 이상         +0.2  (1~2개면 +0.1)
          판례 3개 이상         +0.3  (1~2개면 +0.15)
          보증금 액수 파악됨     +0.2  ← 정확한 비용 계산 가능

        ⚠️ Phase 3 변경: region_data 대신 deposit_amount를 봅니다.
           지역보다 보증금 액수가 답변 정확도에 더 직접적입니다.
        """
        confidence = 0.3

        statutes = search_results.get("statutes", [])
        if len(statutes) >= 3:
            confidence += 0.2
        elif statutes:
            confidence += 0.1

        precedents = search_results.get("precedents", [])
        if len(precedents) >= 3:
            confidence += 0.3
        elif precedents:
            confidence += 0.15

        if deposit_amount:
            confidence += 0.2

        return min(confidence, 1.0)