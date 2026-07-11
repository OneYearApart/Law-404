"""
========================================================================
C파트 Retriever 정확도 회귀 테스트
========================================================================
"""
import pytest
from app.rag.retrievers.c_part import CPartRetriever

TOP_K = 5

# 역산표에서 확정한 질문 4개 + 정답 (data_collection 단계와 동일)
TEST_CASES = [
    pytest.param(
        "계약 끝났는데 보증금을 못 받고 있어요",
        "3의2",
        "2023다202228",
        id="Q1_보증금못받음",
    ),
    pytest.param(
        "이사를 가야 하는데 보증금을 못 받으면 대항력이 사라지나요",
        "3의3",
        "2024다326398",
        id="Q2_임차권등기명령",
    ),
    pytest.param(
        "집이 경매로 넘어갔는데 보증금을 돌려받을 수 있나요",
        "3의2",
        "2025다210305",
        id="Q3_경매배당",
    ),
    pytest.param(
        "소액보증금 최우선변제 대상인지 어떻게 아나요",
        "8",
        None,  # 이 케이스는 판례 사건번호 검증 생략
        id="Q4_소액보증금최우선변제",
    ),
]


@pytest.fixture(scope="module")
def retriever():
    """
    모듈 전체에서 Retriever를 한 번만 생성해서 재사용.
    (OpenAI 클라이언트, DB 커넥션 설정을 테스트마다 새로 만들면 느려짐)
    """
    return CPartRetriever()


@pytest.mark.parametrize("query, expected_statute, expected_case_number", TEST_CASES)
def test_statute_retrieval(retriever, query, expected_statute, expected_case_number):
    """기대하는 조문이 검색 상위 K개 안에 포함되는지 확인"""
    result = retriever.retrieve(query, top_k=TOP_K)

    found_statutes = [
        s.statute_number + (f"의{s.statute_branch}" if s.statute_branch else "")
        for s in result["statutes"]
    ]

    assert expected_statute in found_statutes, (
        f"'{query}' 검색 시 제{expected_statute}조가 상위 {TOP_K}개에 없음. "
        f"실제 결과: {found_statutes}"
    )


@pytest.mark.parametrize("query, expected_statute, expected_case_number", TEST_CASES)
def test_precedent_retrieval(retriever, query, expected_statute, expected_case_number):
    """기대하는 판례가 검색 상위 K개 안에 포함되는지 확인 (기대값 없으면 스킵)"""
    if expected_case_number is None:
        pytest.skip("이 질문은 판례 사건번호 검증 대상이 아님")

    result = retriever.retrieve(query, top_k=TOP_K)
    found_cases = [p.case_number for p in result["precedents"]]

    assert expected_case_number in found_cases, (
        f"'{query}' 검색 시 판례 {expected_case_number}가 상위 {TOP_K}개에 없음. "
        f"실제 결과: {found_cases}"
    )