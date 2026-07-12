"""
========================================================================
C파트 Retriever 정확도 검증
========================================================================
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

from c_part import CPartRetriever

logging.basicConfig(level=logging.WARNING)  # retriever 내부 로그는 잠시 끔 (결과만 깔끔하게 보려고)
logger = logging.getLogger(__name__)


@dataclass
class TestCase:
    """
    검증용 테스트 케이스 하나.
    question_id, 질문, 그리고 "이 답이 나와야 한다"는 기대값으로 구성됩니다.
    """
    question_id: str
    query: str
    expected_statute: Optional[str]   # 예: "3의2" (조문번호+가지번호)
    expected_case_number: Optional[str]  # 예: "2023다202228"


# 역산표에서 확정했던 4개 질문 + 우리가 직접 선정했던 정답
# (data_collection 단계에서 확정한 값과 100% 동일하게 맞춰야 검증 의미가 있음)
TEST_CASES = [
    TestCase(
        question_id="Q1_보증금못받음",
        query="계약 끝났는데 보증금을 못 받고 있어요",
        expected_statute="3의2",          # 제3조의2 (보증금의 회수)
        expected_case_number="2023다202228",  # 241081
    ),
    TestCase(
        question_id="Q2_임차권등기명령",
        query="이사를 가야 하는데 보증금을 못 받으면 대항력이 사라지나요",
        expected_statute="3의3",          # 제3조의3 (임차권등기명령)
        expected_case_number="2024다326398",  # 605771
    ),
    TestCase(
        question_id="Q3_경매배당",
        query="집이 경매로 넘어갔는데 보증금을 돌려받을 수 있나요",
        expected_statute="3의2",          # 제3조의2 (보증금의 회수 - 우선변제)
        expected_case_number="2025다210305",  # 618185
    ),
    TestCase(
        question_id="Q4_소액보증금최우선변제",
        query="소액보증금 최우선변제 대상인지 어떻게 아나요",
        expected_statute="8",             # 제8조 (보증금 중 일정액의 보호)
        expected_case_number=None,        # 240307의 정확한 사건번호는 판례내용에서 재확인 필요
    ),
]

TOP_K = 5  # 상위 몇 개 안에 들면 "찾았다"로 인정할지


def check_statute_hit(test_case: TestCase, statutes: List) -> bool:
    """기대하는 조문이 검색 결과 상위 K개 안에 있는지 확인"""
    if not test_case.expected_statute:
        return True  # 기대값이 없으면 검증 생략

    for s in statutes:
        조문표시 = s.statute_number + (f"의{s.statute_branch}" if s.statute_branch else "")
        if 조문표시 == test_case.expected_statute:
            return True
    return False


def check_case_hit(test_case: TestCase, precedents: List) -> bool:
    """기대하는 판례가 검색 결과 상위 K개 안에 있는지 확인"""
    if not test_case.expected_case_number:
        return True

    for p in precedents:
        if p.case_number == test_case.expected_case_number:
            return True
    return False


def run_validation():
    retriever = CPartRetriever()

    total = len(TEST_CASES)
    statute_hits = 0
    case_hits = 0

    print("=" * 70)
    print(f"C파트 Retriever 정확도 검증 (top_k={TOP_K})")
    print("=" * 70)

    for tc in TEST_CASES:
        result = retriever.retrieve(tc.query, top_k=TOP_K)

        statute_ok = check_statute_hit(tc, result["statutes"])
        case_ok = check_case_hit(tc, result["precedents"])

        statute_hits += int(statute_ok)
        case_hits += int(case_ok)

        print(f"\n[{tc.question_id}] {tc.query}")
        print(f"  조문 기대값: 제{tc.expected_statute}조" if tc.expected_statute else "  조문 기대값: (없음)")
        print(f"  → 검색 결과: {[s.statute_number + (f'의{s.statute_branch}' if s.statute_branch else '') for s in result['statutes']]}")
        print(f"  → {'✅ 일치' if statute_ok else '❌ 불일치'}")

        if tc.expected_case_number:
            print(f"  판례 기대값: {tc.expected_case_number}")
            print(f"  → 검색 결과: {[p.case_number for p in result['precedents']]}")
            print(f"  → {'✅ 일치' if case_ok else '❌ 불일치'}")

    print("\n" + "=" * 70)
    print(f"조문 정확도: {statute_hits}/{total} ({statute_hits/total*100:.0f}%)")
    print(f"판례 정확도: {case_hits}/{total} ({case_hits/total*100:.0f}%)")
    print("=" * 70)

    if statute_hits < total or case_hits < total:
        print("\n⚠️  일부 항목이 상위권에 없습니다. 다음을 점검해보세요:")
        print("   1. 청킹 단위가 너무 크거나 작지 않은지")
        print("   2. 질문 문장과 조문/판례 문장의 표현 차이가 너무 크지 않은지")
        print("   3. top_k를 늘려서 몇 위에 있는지 확인 (완전히 없는 것과 순위가 낮은 건 다른 문제)")


if __name__ == "__main__":
    run_validation()