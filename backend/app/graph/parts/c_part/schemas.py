"""
【App 모델】C파트 답변 생성 Agent 입출력 스키마

"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

# ════════════════════════════════════════════════════════════════════════════════
# 【입력 스키마】
# ════════════════════════════════════════════════════════════════════════════════


class Message(BaseModel):
    """
    대화 히스토리 메시지 (conversations 테이블과 동일)

    지금: None (비사용)
    나중: repository에서 가져올 chat_history에 사용
    """

    role: str  # "user" | "assistant"
    content: str


class RetrievalResult(BaseModel):
    """Retriever 결과"""

    statutes: list[dict]  # [{"article_number": "3조", "content": "...", ...}, ...]
    precedents: list[
        dict
    ]  # [{"case_number": "2023다202228", "content": "...", ...}, ...]


class RegionData(BaseModel):
    """region_standards 에서 조회한 데이터"""

    region: str
    small_deposit_threshold: int
    lawyer_fee_rate_min: int
    lawyer_fee_rate_max: int
    data_source: str


class AnswerGeneratorInput(BaseModel):
    """
    AnswerGeneratorAgent의 입력값

    """

    question: str = Field(..., description="사용자 질문")
    search_results: RetrievalResult = Field(..., description="RAG retriever 검색 결과")
    region_data: Optional[RegionData] = Field(None, description="지역별 표준 정보")
    chat_history: Optional[list[Message]] = Field(
        None, description="대화 히스토리 (나중에 추가)"
    )
    user_id: Optional[int] = Field(None, description="사용자 ID (대화 저장용)")


# ════════════════════════════════════════════════════════════════════════════════
# 【출력 스키마】7개 섹션
# ════════════════════════════════════════════════════════════════════════════════


class AnswerSection(BaseModel):
    """
    하나의 답변 섹션

    """

    title: str = Field(..., description="섹션 제목")
    content: str = Field(..., description="섹션 내용 (사용자 친화적, 쉬운 말)")
    citations: list[str] = Field(
        default_factory=list, description="근거 출처 (조문/판례 사건번호)"
    )


class AnswerOutput(BaseModel):
    """
    최종 답변

    7개 섹션 + 메타데이터

    """

    # 【7개 섹션】
    situation: AnswerSection = Field(..., description="상황 진단 - 법적 상황 설명")
    legal_basis: AnswerSection = Field(
        ..., description="관련 법 조문 - 조문 원문 + 해석"
    )
    precedents: AnswerSection = Field(..., description="관련 판례 - 판례 분석 + 유사점")
    action_steps: AnswerSection = Field(
        ..., description="구체적 행동 절차 - 단계별 가이드"
    )
    expected_cost: AnswerSection = Field(
        ..., description="예상 비용 - 경로별 비용 계산"
    )
    anticipated_disputes: AnswerSection = Field(
        ..., description="임대인 반박 & 대응 - 예상 분쟁 대응"
    )

    # 【FAQ】
    follow_up_questions: list[str] = Field(..., description="자주 묻는 질문 (FAQ)")

    # 【메타데이터】
    question: str = Field(..., description="원래 질문")
    generated_at: datetime = Field(
        default_factory=datetime.now, description="생성 시간"
    )
    confidence_score: float = Field(
        ..., description="신뢰도 점수 (0.0~1.0, 근거 데이터 충분도)"
    )
    model_used: str = Field(default="claude-opus-4-6", description="사용된 LLM 모델")
