"""
【Phase 3: 실제 GPT API 테스트】Q1~Q4 통합 테스트
"""

import pytest
import pytest_asyncio
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path


# ════════════════════════════════════════════════════════════════════════════════
# 【Q1~Q4 테스트 케이스 정의】
# ════════════════════════════════════════════════════════════════════════════════

TEST_CASES = {
    "Q1_보증금_미반환": {
        "question": "보증금을 못 받았을 때 어떻게 해야 하나요?",
        "category": "보증금 반환",
        "description": "기본적인 보증금 미반환 상황",
        "search_query": "보증금 미반환 반환 청구",
        "expected_sections": ["situation", "legal_basis", "precedents", "action_steps", "expected_cost"],
        "min_confidence": 0.7  # 가장 근거가 많은 질문이므로 기준 높음
    },

    "Q2_임차권등기명령": {
        "question": "임차권등기명령이 뭐고 어떻게 신청하나요?",
        "category": "임차권등기명령",
        "description": "임차권등기명령 신청 절차",
        "search_query": "임차권등기명령 신청 절차",
        "expected_sections": ["situation", "legal_basis", "action_steps"],
        "min_confidence": 0.65
    },

    "Q3_경매_배당": {
        "question": "경매가 나갔는데 보증금을 받을 수 있나요?",
        "category": "경매 배당",
        "description": "경매 상황에서의 보증금 배당",
        "search_query": "경매 배당 보증금",
        "expected_sections": ["situation", "legal_basis", "precedents"],
        "min_confidence": 0.6  # 판례가 상대적으로 적어서 기준 낮춤
    },

    "Q4_소액보증금": {
        "question": "보증금이 적은데도 보호받나요?",
        "category": "소액보증금",
        "description": "소액보증금 최우선변제권",
        "search_query": "소액보증금 최우선변제권",
        "expected_sections": ["situation", "legal_basis", "action_steps"],
        "min_confidence": 0.65
    },

    "Q5_금액포함": {
        "question": "보증금 5천만원을 못 받았는데 소송하면 비용이 얼마나 드나요?",
        "category": "비용 계산",
        "description": "보증금 액수가 명시된 경우 - 정확한 비용 계산 검증",
        "search_query": "보증금 반환 소송 비용",
        "expected_sections": ["situation", "legal_basis", "action_steps", "expected_cost"],
        "min_confidence": 0.7
},
}

# ════════════════════════════════════════════════════════════════════════════════
# 【변환 함수】Retriever 결과 → Agent 입력 형식
# ════════════════════════════════════════════════════════════════════════════════

def convert_search_results(chunks: list) -> dict:
    """
    【변환】list[RetrievedChunk] → {"statutes": [...], "precedents": [...]}

    RetrievedChunk 필드:
    - source_type: 'statute' 또는 'precedent'  ← 이걸로 구분
    - content: 본문
    - statute_number, statute_branch, statute_title: 조문 정보
    - case_number, case_name, case_date: 판례 정보
    - similarity: 유사도 점수

    Args:
        chunks: retriever.search()의 반환값

    Returns:
        {"statutes": [dict, ...], "precedents": [dict, ...]}
    """
    statutes = []
    precedents = []

    for chunk in chunks:
        # 【조문】source_type이 'statute'
        if chunk.source_type == "statute":
            # 【조문번호 조립】"8" + branch → "8" 또는 "3의2"
            # statute_branch가 있으면 "제3조의2" 형태
            article_num = chunk.statute_number or ""
            if chunk.statute_branch:
                article_num = f"{article_num}조의{chunk.statute_branch}"
            else:
                article_num = f"{article_num}조"

            statutes.append({
                "article_number": article_num,
                "title": chunk.statute_title or "",
                "content": chunk.content,
                "similarity": chunk.similarity,
            })

        # 【판례】source_type이 'precedent'
        elif chunk.source_type == "precedent":
            precedents.append({
                "case_number": chunk.case_number or "",
                "case_name": chunk.case_name or "",
                "case_date": str(chunk.case_date) if chunk.case_date else "",
                "content": chunk.content,
                "similarity": chunk.similarity,
                # ⚠️ court_level, case_year, ruling_type은 RetrievedChunk에 없음
                #    → Agent의 format_precedents_context()가 이걸 참조하므로
                #      기본값을 넣어줘야 KeyError 안 남
                "court_level": 0,
                "case_year": "",
                "ruling_type": "",
            })

    return {"statutes": statutes, "precedents": precedents}

# ════════════════════════════════════════════════════════════════════════════════
# 【실제 통합 테스트】GPT-4o API 호출
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestPhase3Integration:
    """
    【Phase 3 실제 통합 테스트】

    """

    # ────────────────────────────────────────────────────────────────────────
    # 【Fixtures】테스트에 필요한 객체 준비
    # ────────────────────────────────────────────────────────────────────────

    @pytest_asyncio.fixture
    async def graph(self):
        """
        【Fixture】실제 GPT-4o 그래프 생성


        """
        from app.graph.parts.c_part.builder import get_c_part_graph
        return get_c_part_graph()

    @pytest_asyncio.fixture
    async def retriever(self):
        """
        【Fixture】실제 Retriever 생성

        """
        from app.rag.retrievers.c_part import CPartRetriever
        return CPartRetriever()

    # ────────────────────────────────────────────────────────────────────────
    # 【Q1】보증금 미반환
    # ────────────────────────────────────────────────────────────────────────

    async def test_q1_보증금_미반환(self, graph, retriever):
        """
        【Test Q1】보증금 미반환 - 가장 기본적인 사례


        """
        test_case = TEST_CASES["Q1_보증금_미반환"]


        print(f"\n【Step 1】검색 중: {test_case['search_query']}")
        raw_chunks = retriever.search(test_case["search_query"])
        search_results = convert_search_results(raw_chunks)
        print(f"   조문 {len(search_results.get('statutes', []))}개, "
              f"판례 {len(search_results.get('precedents', []))}개 검색됨")


        print(f"【Step 2】GPT-4o 호출 중... (10~20초 소요)")
        start_time = time.time()

        result = await graph.ainvoke({
            "question": test_case["question"],
            "search_results": search_results,
            "chat_history": None,               # conversations repository 완성되면 연결
            "user_id": None
        })

        elapsed = time.time() - start_time
        print(f"   완료 ({elapsed:.1f}초)")

        answer = result.get("answer", {})

        assert answer, f"❌ 답변이 생성되지 않음. error: {result.get('error')}"

        assert answer.get("is_off_topic") != True, \
            f"❌ 관련 질문인데 off-topic으로 분류됨: {answer.get('message')}"

        confidence = answer.get("confidence_score", 0)
        assert confidence >= test_case["min_confidence"], \
            f"❌ 신뢰도 미달: {confidence:.2f} < {test_case['min_confidence']}"

        for section in test_case["expected_sections"]:
            assert section in answer, f"❌ 섹션 누락: {section}"
            assert answer[section].get("content"), f"❌ 섹션 내용 비어있음: {section}"

        assert len(answer.get("follow_up_questions", [])) > 0, "❌ FAQ 없음"

        self._save_result(test_case, answer, elapsed)

        print(f"✅ {test_case['category']} 통과 | 신뢰도 {confidence:.2f} | {elapsed:.1f}초")

    # ────────────────────────────────────────────────────────────────────────
    # 【Q2】임차권등기명령
    # ────────────────────────────────────────────────────────────────────────

    async def test_q2_임차권등기명령(self, graph, retriever):
        """
        【Test Q2】임차권등기명령

        """
        test_case = TEST_CASES["Q2_임차권등기명령"]

        raw_chunks = retriever.search(test_case["search_query"])
        search_results = convert_search_results(raw_chunks)
        

        start_time = time.time()
        result = await graph.ainvoke({
            "question": test_case["question"],
            "search_results": search_results,
            "chat_history": None,
            "user_id": None
        })
        elapsed = time.time() - start_time

        answer = result.get("answer", {})

        assert answer, f"❌ 답변 없음. error: {result.get('error')}"
        assert answer.get("is_off_topic") != True, "❌ off-topic으로 잘못 분류됨"

        confidence = answer.get("confidence_score", 0)
        assert confidence >= test_case["min_confidence"], \
            f"❌ 신뢰도 미달: {confidence:.2f}"

        for section in test_case["expected_sections"]:
            assert section in answer, f"❌ 섹션 누락: {section}"
            assert answer[section].get("content"), f"❌ 섹션 비어있음: {section}"

        self._save_result(test_case, answer, elapsed)

        print(f"✅ {test_case['category']} 통과 | 신뢰도 {confidence:.2f} | {elapsed:.1f}초")

    # ────────────────────────────────────────────────────────────────────────
    # 【Q3】경매 배당
    # ────────────────────────────────────────────────────────────────────────

    async def test_q3_경매_배당(self, graph, retriever):
        """
        【Test Q3】경매 배당


        """
        test_case = TEST_CASES["Q3_경매_배당"]

        raw_chunks = retriever.search(test_case["search_query"])
        search_results = convert_search_results(raw_chunks)

        start_time = time.time()
        result = await graph.ainvoke({
            "question": test_case["question"],
            "search_results": search_results,
            "chat_history": None,
            "user_id": None
        })
        elapsed = time.time() - start_time

        answer = result.get("answer", {})

        assert answer, f"❌ 답변 없음. error: {result.get('error')}"
        assert answer.get("is_off_topic") != True, "❌ off-topic으로 잘못 분류됨"

        confidence = answer.get("confidence_score", 0)
        assert confidence >= test_case["min_confidence"], \
            f"❌ 신뢰도 미달: {confidence:.2f}"

        for section in test_case["expected_sections"]:
            assert section in answer, f"❌ 섹션 누락: {section}"
            assert answer[section].get("content"), f"❌ 섹션 비어있음: {section}"

        self._save_result(test_case, answer, elapsed)

        print(f"✅ {test_case['category']} 통과 | 신뢰도 {confidence:.2f} | {elapsed:.1f}초")

    # ────────────────────────────────────────────────────────────────────────
    # 【Q4】소액보증금
    # ────────────────────────────────────────────────────────────────────────

    async def test_q4_소액보증금(self, graph, retriever):
        """
        【Test Q4】소액보증금 최우선변제권

        """
        test_case = TEST_CASES["Q4_소액보증금"]

        raw_chunks = retriever.search(test_case["search_query"])
        search_results = convert_search_results(raw_chunks)

        start_time = time.time()
        result = await graph.ainvoke({
            "question": test_case["question"],
            "search_results": search_results,
            "chat_history": None,
            "user_id": None
        })
        elapsed = time.time() - start_time

        answer = result.get("answer", {})

        assert answer, f"❌ 답변 없음. error: {result.get('error')}"
        assert answer.get("is_off_topic") != True, "❌ off-topic으로 잘못 분류됨"

        confidence = answer.get("confidence_score", 0)
        assert confidence >= test_case["min_confidence"], \
            f"❌ 신뢰도 미달: {confidence:.2f}"

        for section in test_case["expected_sections"]:
            assert section in answer, f"❌ 섹션 누락: {section}"
            assert answer[section].get("content"), f"❌ 섹션 비어있음: {section}"

        self._save_result(test_case, answer, elapsed)

        print(f"✅ {test_case['category']} 통과 | 신뢰도 {confidence:.2f} | {elapsed:.1f}초")
    # ────────────────────────────────────────────────────────────────────────
    # 【Q5】비용 계산 검증
    # ────────────────────────────────────────────────────────────────────────

    async def test_q5_비용계산(self, graph, retriever):
        """
        【Test Q5】비용 계산 검증

        """
        test_case = TEST_CASES["Q5_금액포함"]

        search_results = convert_search_results(
            retriever.search(test_case["search_query"])
        )

        start_time = time.time()
        result = await graph.ainvoke({
            "question": test_case["question"],
            "search_results": search_results,
            "chat_history": None,
            "user_id": None,
        })
        elapsed = time.time() - start_time

        answer = result.get("answer", {})

        assert answer, f"❌ 답변 없음. error: {result.get('error')}"
        assert answer.get("is_off_topic") != True


        deposit = answer.get("deposit_amount")
        assert deposit == 50_000_000, \
            f"❌ 보증금 추출 실패: {deposit} (기대: 50,000,000)"


        cost_text = answer.get("expected_cost", {}).get("content", "")

        cost_text = answer.get("expected_cost", {}).get("content", "")


        assert "395,000" in cost_text, \
            f"❌ 일반소송 비용 395,000원이 없습니다.\n답변: {cost_text[:200]}"

        assert "43,400" in cost_text, \
            f"❌ 임차권등기명령 43,400원이 없습니다"


        import re
        amounts = set(re.findall(r"[\d,]{5,}\s*원", cost_text))
        allowed = {"43,400원", "230,000원", "165,000원", "395,000원", "438,400원"}
        suspicious = {a.replace(" ", "") for a in amounts} - allowed
        if suspicious:
            print(f"   ⚠️ 확인 필요한 금액: {suspicious}")

    # ────────────────────────────────────────────────────────────────────────
    # 【헬퍼 메서드】결과 저장
    # ────────────────────────────────────────────────────────────────────────

    def _save_result(self, test_case, answer, elapsed_time=0.0):


        output_dir = Path("test_results/phase3")
        output_dir.mkdir(parents=True, exist_ok=True)


        test_name = test_case["category"].replace(" ", "_")
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = output_dir / f"{test_name}_{timestamp}.json"


        data = {
            "question": test_case["question"],
            "category": test_case["category"],
            "description": test_case["description"],
            "generated_at": datetime.now().isoformat(),
            "confidence_score": answer.get("confidence_score"),
            "elapsed_time": round(elapsed_time, 2),  # 응답 시간 (성능 분석용)


            "sections": {
                "situation": {
                    "content_length": len(answer.get("situation", {}).get("content", "")),
                    "citations_count": len(answer.get("situation", {}).get("citations", []))
                },
                "legal_basis": {
                    "content_length": len(answer.get("legal_basis", {}).get("content", "")),
                    "citations_count": len(answer.get("legal_basis", {}).get("citations", []))
                },
                "precedents": {
                    "content_length": len(answer.get("precedents", {}).get("content", "")),
                    "citations_count": len(answer.get("precedents", {}).get("citations", []))
                },
                "action_steps": {
                    "content_length": len(answer.get("action_steps", {}).get("content", "")),
                    "citations_count": len(answer.get("action_steps", {}).get("citations", []))
                },
                "expected_cost": {
                    "content_length": len(answer.get("expected_cost", {}).get("content", "")),
                    "citations_count": len(answer.get("expected_cost", {}).get("citations", []))
                },
                "anticipated_disputes": {
                    "content_length": len(answer.get("anticipated_disputes", {}).get("content", "")),
                    "citations_count": len(answer.get("anticipated_disputes", {}).get("citations", []))
                }
            },

            "faq_count": len(answer.get("follow_up_questions", [])),

            "answer_text": {
                "situation": answer.get("situation", {}).get("content", ""),
                "legal_basis": answer.get("legal_basis", {}).get("content", ""),
                "precedents": answer.get("precedents", {}).get("content", ""),
                "action_steps": answer.get("action_steps", {}).get("content", ""),
                "expected_cost": answer.get("expected_cost", {}).get("content", ""),
                "anticipated_disputes": answer.get("anticipated_disputes", {}).get("content", ""),
                "follow_up_questions": answer.get("follow_up_questions", [])
            }
        }

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"   💾 저장: {output_file.name}")


# ════════════════════════════════════════════════════════════════════════════════
# 【Off-topic 테스트】Classifier가 무관한 질문을 걸러내는지 확인
# ════════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_off_topic_question():
    """
    【Off-topic 테스트】무관한 질문 필터링

    """
    from app.graph.parts.c_part.builder import get_c_part_graph

    graph = get_c_part_graph()

    print("\n【Off-topic 테스트】'오늘 날씨 어때요?'")

    result = await graph.ainvoke({
        "question": "오늘 날씨 어때요?",
        "search_results": {"statutes": [], "precedents": []},  # 검색 결과 없어도 됨
        "region_data": None,
        "chat_history": None,
        "user_id": None
    })

    answer = result.get("answer", {})

    assert answer.get("is_off_topic") == True, \
        f"❌ 날씨 질문이 관련 질문으로 통과됨! Classifier 프롬프트 점검 필요"

    assert answer.get("message"), "❌ 안내 메시지 없음"

    assert result.get("situation_section") is None, \
        "❌ off-topic인데 7단계가 실행됨! 조건부 엣지 점검 필요"

    print(f"✅ Off-topic 필터링 정상 작동")
    print(f"   안내 메시지: {answer.get('message', '')[:50]}...")