"""
【테스트】C파트 답변 생성 Agent 테스트

"""

import pytest
import pytest_asyncio
from datetime import datetime
import asyncio

# Import (나중에 실제 경로로 수정)
# from app.graph.parts.c_part.agents.answer_generator import (
#     AnswerGeneratorAgent, 
#     validate_forbidden_phrases,
#     extract_citations
# )
# from app.graph.parts.c_part.graph import build_c_part_graph


# ════════════════════════════════════════════════════════════════════════════════
# 【Mock LLM】테스트용 모의 LLM
# ════════════════════════════════════════════════════════════════════════════════

class MockResponse:
    def __init__(self, content: str):
        self.content = content


class MockLLM:
    """
    테스트용 모의 LLM
    
    실제 LLM 호출 대신 미리 정한 응답을 반환
    """
    
    def __init__(self, mode: str = "safe"):
        """
        Args:
            mode: "safe" (정상 응답) / "forbidden" (금지된 표현) / "error" (실패)
        """
        self.mode = mode
        self.call_count = 0
    
    async def ainvoke(self, prompt: str) -> MockResponse:
        """
        모의 LLM 응답
        """
        self.call_count += 1
        
        if self.mode == "safe":
            return self._safe_response(prompt)
        elif self.mode == "forbidden":
            return self._forbidden_response(prompt)
        elif self.mode == "error":
            raise Exception("Mock LLM error")
        else:
            raise ValueError(f"Unknown mode: {self.mode}")
    
    def _safe_response(self, prompt: str) -> MockResponse:
        """정상 응답 (금지된 표현 없음)"""
        
        if "상황 진단" in prompt:
            return MockResponse(
                "당신은 임차인으로서 법적으로 보호받을 가능성이 높습니다. "
                "주택임대차보호법 제3조의3에 따라 소액보증금에 대한 최우선변제권이 있습니다. "
                "적절한 절차를 따르면 보증금을 반환받을 수 있습니다."
            )
        
        elif "법 조문" in prompt or "관련 법" in prompt:
            return MockResponse(
                "【제3조의3 - 소액보증금 최우선변제권】\n"
                "[원문]\n"
                "임차인의 보증금은 보증금의 범위 내에서 임차주택 위의 담보권자 및 "
                "기타 채권자에 우선하여 변제되어야 한다.\n\n"
                "쉽게 말하면:\n"
                "임차인이 받지 못한 보증금은 임대인의 다른 빚보다 먼저 갚아줘야 한다는 뜻입니다.\n\n"
                "당신의 상황:\n"
                "보증금이 소액(지역별 기준 이하)이라면 이 조항으로 보호받습니다."
            )
        
        elif "판례" in prompt:
            return MockResponse(
                "【2023다202228 - 대법원 2024.2.29】\n"
                "상황: 임차인이 계약 만료 후 보증금 반환을 요청했으나 임대인이 미루는 사건\n\n"
                "법원의 판단: 임대인은 계약 만료 시 지체 없이 보증금을 반환해야 합니다.\n\n"
                "결론: 임차인 승소. 임대인이 보증금 전액 + 지연이자 지급.\n\n"
                "당신과의 유사점: 당신도 계약 만료 후 요청했다면 이 판례처럼 보호받을 가능성 높습니다."
            )
        
        elif "절차" in prompt or "행동" in prompt:
            return MockResponse(
                "【1단계: 내용증명 발송】\n"
                "- 언제: 지금 바로\n"
                "- 뭘: 보증금 반환 요청 내용증명\n"
                "- 효과: 법적 증거 생성\n\n"
                "【2단계: 임차권등기명령 신청】\n"
                "- 언제: 내용증명 후 1주일 뒤\n"
                "- 어디: 주소지 법원\n"
                "- 기간: 약 2-3주 (빠름)\n"
                "- 비용: 약 70,000~100,000원\n\n"
                "⚠️ 체크리스트:\n"
                "- [ ] 계약서 또는 영수증 준비\n"
                "- [ ] 임대인 연락처 확보"
            )
        
        elif "비용" in prompt:
            return MockResponse(
                "【경로 1: 직접 신청】\n"
                "내용증명: 약 5,000~10,000원\n"
                "임차권등기명령: 약 70,000~100,000원\n"
                "합계: 약 75,000~110,000원\n\n"
                "【경로 2: 변호사 도움】\n"
                "변호사 수수료: 보증금 × 1~3% (지역별)\n"
                "보증금 3,000만원인 경우: 약 300,000~900,000원"
            )
        
        elif "반박" in prompt or "분쟁" in prompt:
            return MockResponse(
                "【반박 1: \"보증금을 이미 반환했다\"】\n"
                "당신의 증거: 영수증, 통장 기록, 내용증명 기록\n"
                "대응: 법원은 임대인이 증거를 제시해야 한다고 판단합니다.\n\n"
                "【반박 2: \"수리비로 공제했다\"】\n"
                "법원의 판단: 임대인이 구체적 증거 제시 필요\n"
                "대응: \"그 손해를 입증하세요\" 요구"
            )
        
        elif "FAQ" in prompt or "질문" in prompt:
            return MockResponse(
                "Q1: \"계약서를 잃어버렸으면?\"\n"
                "A: 전입신고 기록만으로도 충분합니다.\n\n"
                "Q2: \"월세 밀린 게 있으면?\"\n"
                "A: 보증금과 월세는 별도입니다.\n\n"
                "Q3: \"얼마나 시간 걸려?\"\n"
                "A: 임차권등기명령은 2-3주, 소액사건은 1-4개월입니다."
            )
        
        else:
            return MockResponse("Mock response for unknown prompt")
    
    def _forbidden_response(self, prompt: str) -> MockResponse:
        """금지된 표현이 포함된 응답"""
        return MockResponse(
            "이 절차의 성공률은 98%입니다. "
            "보통 2-3개월이 소요되고, 난이도는 1입니다."
        )


# ════════════════════════════════════════════════════════════════════════════════
# 【Unit Test】각 노드별 테스트
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestAnswerGeneratorAgent:
    """AnswerGeneratorAgent 단위 테스트"""
    
    @pytest_asyncio.fixture
    async def mock_agent(self):
        """테스트용 Agent 생성"""
        mock_llm = MockLLM(mode="safe")
        # from app.graph.parts.c_part.agents.answer_generator import AnswerGeneratorAgent
        # return AnswerGeneratorAgent(mock_llm)
        return None  # TODO: 실제 import로 교체
    
    async def test_generate_situation(self, mock_agent):
        """Node 1: 상황 진단 생성 테스트"""
        if not mock_agent:
            pytest.skip("Mock agent not available")
        
        result = await mock_agent.generate_situation(
            question="보증금을 못 받았어요",
            statutes=[{"article_number": "3조", "title": "...", "content": "..."}],
            precedents=[{"case_number": "2023다202228", "court_level": 0, "content": "..."}]
        )
        
        # 검증
        assert result["title"] == "상황 진단"
        assert len(result["content"]) > 0
        assert "보증금" in result["content"] or "법적" in result["content"].lower()
        assert isinstance(result["citations"], list)
    
    async def test_generate_legal_basis(self, mock_agent):
        """Node 2: 법 조문 생성 테스트"""
        if not mock_agent:
            pytest.skip("Mock agent not available")
        
        result = await mock_agent.generate_legal_basis(
            question="보증금을 못 받았어요",
            statutes=[{"article_number": "3조", "title": "...", "content": "..."}],
            situation_content="상황 진단 내용"
        )
        
        assert result["title"] == "관련 법 조문"
        assert len(result["content"]) > 0
    
    async def test_generate_precedents(self, mock_agent):
        """Node 3: 판례 분석 생성 테스트"""
        if not mock_agent:
            pytest.skip("Mock agent not available")
        
        result = await mock_agent.generate_precedents(
            question="보증금을 못 받았어요",
            precedents=[{"case_number": "2023다202228", "court_level": 0, "content": "..."}],
            situation_content="상황 진단 내용"
        )
        
        assert result["title"] == "관련 판례"
        assert len(result["content"]) > 0
    
    async def test_generate_action_steps(self, mock_agent):
        """Node 4: 행동 절차 생성 테스트"""
        if not mock_agent:
            pytest.skip("Mock agent not available")
        
        result = await mock_agent.generate_action_steps(
            question="보증금을 못 받았어요",
            situation_content="상황 진단 내용",
            legal_basis_content="법 조문 내용"
        )
        
        assert result["title"] == "구체적 행동 절차"
        assert len(result["content"]) > 0
        # 절차명이 포함되어야 함
        assert any(step in result["content"].lower() for step in ["내용증명", "절차", "신청"])
    
    async def test_generate_expected_cost_without_region(self, mock_agent):
        """Node 5a: 비용 생성 (지역 정보 없음)"""
        if not mock_agent:
            pytest.skip("Mock agent not available")
        
        result = await mock_agent.generate_expected_cost(
            question="보증금을 못 받았어요",
            action_steps_content="절차 내용",
            region_data=None
        )
        
        assert result["title"] == "예상 비용"
        assert len(result["content"]) > 0
    
    async def test_generate_expected_cost_with_region(self, mock_agent):
        """Node 5b: 비용 생성 (지역 정보 있음)"""
        if not mock_agent:
            pytest.skip("Mock agent not available")
        
        result = await mock_agent.generate_expected_cost(
            question="보증금을 못 받았어요",
            action_steps_content="절차 내용",
            region_data={
                "region": "서울",
                "lawyer_fee_rate_min": 1,
                "lawyer_fee_rate_max": 3
            }
        )
        
        assert result["title"] == "예상 비용"
        assert "지역" in result["content"].lower() or "변호사" in result["content"].lower()
    
    async def test_generate_anticipated_disputes(self, mock_agent):
        """Node 6: 반박 대응 생성 테스트"""
        if not mock_agent:
            pytest.skip("Mock agent not available")
        
        result = await mock_agent.generate_anticipated_disputes(
            question="보증금을 못 받았어요",
            legal_basis_content="법 조문 내용",
            precedents_content="판례 내용",
            situation_content="상황 진단 내용"
        )
        
        assert result["title"] == "임대인 반박 & 대응"
        assert len(result["content"]) > 0
    
    async def test_generate_follow_up_questions(self, mock_agent):
        """Node 7: FAQ 생성 테스트"""
        if not mock_agent:
            pytest.skip("Mock agent not available")
        
        result = await mock_agent.generate_follow_up_questions(
            question="보증금을 못 받았어요",
            situation_content="상황 진단 내용",
            action_steps_content="절차 내용"
        )
        
        assert isinstance(result, list)
        assert len(result) > 0
        # Q&A 형식 확인
        for qa in result:
            assert isinstance(qa, str)

# ════════════════════════════════════════════════════════════════════════════════
# 【금지된 표현 검증】테스트 함수
# ════════════════════════════════════════════════════════════════════════════════
# 위치: 클래스들 사이에 위치
# 왜? 독립적인 함수 테스트이므로 클래스로 묶지 않음
# 들여쓰기: 0 (클래스와 같은 수준)

@pytest.mark.asyncio
async def test_forbidden_phrases_detection():
    """
    【금지된 표현 검증】LLM이 임의 수치를 지어내지 않는지 확인
    
    """
    # from app.graph.parts.c_part.agents.answer_generator import validate_forbidden_phrases
    
    # ────────────────────────────────────────────────────────────────────────
    # 【Test 1: 안전한 텍스트】금지된 표현 없음
    # ────────────────────────────────────────────────────────────────────────
    safe_text = "이 절차는 효율적이며 법적으로 보호받을 가능성이 있습니다."
    # is_safe, violations = validate_forbidden_phrases(safe_text)
    # assert is_safe, "안전한 텍스트가 위반으로 판정됨"
    # assert len(violations) == 0, "위반 사항이 있음"
    
    # ────────────────────────────────────────────────────────────────────────
    # 【Test 2: 성공률 위반】임의의 수치 감지
    # ────────────────────────────────────────────────────────────────────────
    forbidden_text = "이 절차의 성공률은 98%입니다."
    # is_safe, violations = validate_forbidden_phrases(forbidden_text)
    # assert not is_safe, "성공률이 감지되지 않음"
    # assert any("성공률" in v for v in violations), "성공률 위반이 반영되지 않음"
    
    # ────────────────────────────────────────────────────────────────────────
    # 【Test 3: 기간 위반】임의의 기간 감지
    # ────────────────────────────────────────────────────────────────────────
    forbidden_text2 = "보통 2-3개월이 소요됩니다."
    # is_safe, violations = validate_forbidden_phrases(forbidden_text2)
    # assert not is_safe, "기간 표현이 감지되지 않음"
    # assert any("기간" in v for v in violations), "기간 위반이 반영되지 않음"


# ════════════════════════════════════════════════════════════════════════════════
# 【Topic Classifier 테스트】분류기 기능 검증
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestTopicClassifier:
    """
    【Topic Classifier 테스트 클래스】
    
    """
    
    @pytest_asyncio.fixture
    async def mock_agent_for_classifier(self):
        """
        【Fixture】Classifier용 Mock Agent 생성
        
        """
        mock_llm = MockLLM(mode="safe")
        # TODO: 실제 배포 후 다음과 같이 변경
        # from app.graph.parts.c_part.agents.answer_generator import AnswerGeneratorAgent
        # return AnswerGeneratorAgent(mock_llm)
        return None  # 지금은 import 불가능하므로 None 반환
    
    # ────────────────────────────────────────────────────────────────────────
    # 【On-topic 테스트들】카테고리3 관련 질문
    # ────────────────────────────────────────────────────────────────────────
    # 이 테스트들은 "보증금 반환, 경매, 배당" 관련 질문이
    # 정확히 분류되는지 확인함
    
    async def test_classify_relevant_deposit(self, mock_agent_for_classifier):
        """
        【테스트】Q1 보증금 미반환 - 관련 질문 분류

        """
        if not mock_agent_for_classifier:
            pytest.skip("Mock agent not available")
        
        # 【테스트 실행】
        result = await mock_agent_for_classifier.classify_topic(
            question="보증금을 못 받았어요"
        )
        
        # 【검증】
        # 관련 질문이므로 is_relevant = True
        assert result["is_relevant"] == True, "보증금 질문이 관련으로 분류되지 않음"
        
        # 신뢰도가 충분히 높은지 확인 (0.8 이상)
        # 왜 0.8? 명확한 질문이므로 거의 확실해야 함
        assert result["confidence"] > 0.8, f"신뢰도 낮음: {result['confidence']}"
    
    async def test_classify_relevant_registry(self, mock_agent_for_classifier):
        """
        【테스트】Q2 임차권등기명령 - 관련 질문 분류
        
        """
        if not mock_agent_for_classifier:
            pytest.skip("Mock agent not available")
        
        result = await mock_agent_for_classifier.classify_topic(
            question="임차권등기명령이 뭐고 어떻게 신청하나요?"
        )
        
        assert result["is_relevant"] == True, "임차권등기명령 질문이 관련으로 분류되지 않음"
        assert result["confidence"] > 0.8
    
    async def test_classify_relevant_auction(self, mock_agent_for_classifier):
        """
        【테스트】Q3 경매 배당 - 관련 질문 분류
        
        """
        if not mock_agent_for_classifier:
            pytest.skip("Mock agent not available")
        
        result = await mock_agent_for_classifier.classify_topic(
            question="경매가 나갔는데 보증금을 받을 수 있나요?"
        )
        
        assert result["is_relevant"] == True, "경매 질문이 관련으로 분류되지 않음"
    
    # ────────────────────────────────────────────────────────────────────────
    # 【Off-topic 테스트들】무관한 질문
    # ────────────────────────────────────────────────────────────────────────
    # 이 테스트들은 "날씨, 요리, 프로그래밍" 같은 무관한 질문이
    # 정확히 필터링되는지 확인함
    # 왜 중요? 비용 절감의 핵심! (7배 비용 절감)
    
    async def test_classify_off_topic_weather(self, mock_agent_for_classifier):
        """
        【테스트】무관한 질문 - 날씨

        """
        if not mock_agent_for_classifier:
            pytest.skip("Mock agent not available")
        
        result = await mock_agent_for_classifier.classify_topic(
            question="오늘 날씨 어때요?"
        )
        
        # 무관한 질문이므로 False
        assert result["is_relevant"] == False, "날씨 질문이 통과됨"
    
    async def test_classify_off_topic_coding(self, mock_agent_for_classifier):
        """
        【테스트】무관한 질문 - 프로그래밍
        """
        if not mock_agent_for_classifier:
            pytest.skip("Mock agent not available")
        
        result = await mock_agent_for_classifier.classify_topic(
            question="파이썬 코드 작성해주세요"
        )
        
        assert result["is_relevant"] == False, "프로그래밍 질문이 통과됨"
    
    async def test_classify_off_topic_category1(self, mock_agent_for_classifier):
        """
        【테스트】무관한 질문 - 카테고리1 (계약 체결)
        
        """
        if not mock_agent_for_classifier:
            pytest.skip("Mock agent not available")
        
        result = await mock_agent_for_classifier.classify_topic(
            question="계약 체결할 때 뭘 확인해야 하나요?"
        )
        
        # 임대차 관련이지만 카테고리3이 아니므로 False
        assert result["is_relevant"] == False, "카테고리1 질문이 통과됨"


# ════════════════════════════════════════════════════════════════════════════════
# 【Integration Test】Q1~Q4 전체 흐름 (기존)
# ════════════════════════════════════════════════════════════════════════════════
# 위치: TestTopicClassifier 다음
# 왜? 개별 테스트 → 전체 흐름 테스트 순서

@pytest.mark.asyncio
class TestAnswerGeneratorIntegration:
    """
    【Integration 테스트】전체 파이프라인 검증
    """
    @pytest_asyncio.fixture
    async def mock_graph(self):
        """테스트용 그래프 생성"""
        mock_llm = MockLLM(mode="safe")
        # from app.graph.parts.c_part.graph import build_c_part_graph
        # return build_c_part_graph(mock_llm)
        return None  # TODO: 실제 import로 교체
    
    async def test_full_answer_q1(self, mock_graph):
        """Q1: 보증금 미반환 - 전체 흐름"""
        if not mock_graph:
            pytest.skip("Mock graph not available")
        
        input_data = {
            "question": "보증금을 못 받았을 때 어떻게 해야 하나요?",
            "search_results": {
                "statutes": [
                    {"article_number": "3조", "title": "...", "content": "..."},
                    {"article_number": "3조의3", "title": "...", "content": "..."}
                ],
                "precedents": [
                    {"case_number": "2023다202228", "court_level": 0, "case_year": 2024, "content": "..."}
                ]
            },
            "region_data": {"region": "서울", "lawyer_fee_rate_min": 1, "lawyer_fee_rate_max": 3},
            "chat_history": None,
            "user_id": 123
        }
        
        result = await mock_graph.ainvoke(input_data)
        
        # 검증
        answer = result.get("answer")
        assert answer is not None
        
        # 모든 섹션 존재 확인
        assert answer.get("situation", {}).get("content")
        assert answer.get("legal_basis", {}).get("content")
        assert answer.get("precedents", {}).get("content")
        assert answer.get("action_steps", {}).get("content")
        assert answer.get("expected_cost", {}).get("content")
        assert answer.get("anticipated_disputes", {}).get("content")
        assert len(answer.get("follow_up_questions", [])) > 0
        
        # 신뢰도 확인
        assert 0 <= answer["confidence_score"] <= 1.0
        assert answer["confidence_score"] > 0.5  # Q1은 근거 충분하므로 신뢰도 높음
    
    async def test_q2_임차권등기명령(self, mock_graph):
        """Q2: 임차권등기명령"""
        if not mock_graph:
            pytest.skip("Mock graph not available")
        
        # 테스트 구조는 Q1과 동일
        input_data = {
            "question": "임차권등기명령이 뭐고 어떻게 신청하나요?",
            "search_results": {"statutes": [...], "precedents": [...]},
            "region_data": None,
            "chat_history": None,
            "user_id": 123
        }
        
        # result = await mock_graph.ainvoke(input_data)
        # assert result.get("answer") is not None
    
    async def test_q3_경매배당(self, mock_graph):
        """Q3: 경매 배당"""
        if not mock_graph:
            pytest.skip("Mock graph not available")
        
        pass  # 구조 동일
    
    async def test_q4_소액보증금(self, mock_graph):
        """Q4: 소액보증금"""
        if not mock_graph:
            pytest.skip("Mock graph not available")
    pass


# ════════════════════════════════════════════════════════════════════════════════
# 【실행】pytest 커맨드 라인 실행
# ════════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    """
    【직접 실행】Python으로 파일 직접 실행 시
    
    역할:
    - `python tests/c_part/test_answer_generator.py` 커맨드 사용 가능
    - 또는 `pytest tests/c_part/test_answer_generator.py -v` 권장
    """
    pytest.main([__file__, "-v"])