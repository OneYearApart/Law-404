"""
【FastAPI 라우터】C파트 - 보증금 반환·경매·배당
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.graph.parts.c_part.builder import get_c_part_graph
from app.rag.retrievers.c_part import CPartRetriever
from app.rag.repositories.cost_repository import CostRepository
from app.rag.ingestion.clova_ocr import ClovaOCR

import json
from fastapi import UploadFile, File, Form
#from app.graph.parts.c_part.agents.ocr import ContractOCR

from app.graph.parts.c_part.agents.document_agent import (
    DocumentAgent,
    REQUIRED_FIELDS,
)
from langchain_openai import ChatOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/c-part", tags=["C파트 - 보증금 반환"])


_graph = None
_retriever = None
_cost_repo = None
_doc_agent = None
# _ocr = None


def _get_graph():
    """【싱글턴】그래프 인스턴스 (처음 한 번만 생성)"""
    global _graph
    if _graph is None:
        logger.info("[C파트] 그래프 초기화 중...")
        _graph = get_c_part_graph()
        logger.info("[C파트] 그래프 준비 완료")
    return _graph


def _get_retriever():
    """【싱글턴】Retriever 인스턴스"""
    global _retriever
    if _retriever is None:
        logger.info("[C파트] Retriever 초기화 중...")
        _retriever = CPartRetriever()
        logger.info("[C파트] Retriever 준비 완료")
    return _retriever


def _get_cost_repo():
    """【싱글턴】CostRepository 인스턴스"""
    global _cost_repo
    if _cost_repo is None:
        _cost_repo = CostRepository()
    return _cost_repo

def _get_doc_agent():
    """
    【싱글턴】DocumentAgent 인스턴스
 
    ⚠️ 왜 별도 LLM을 만드나?
       상담용 그래프의 LLM은 temperature=0.7입니다 (창의적).
       문서 생성은 temperature를 낮춰야 합니다 (정확성).
       → 법적 문서에 창의성은 독입니다.
    """
    global _doc_agent
    if _doc_agent is None:
        logger.info("[C파트] DocumentAgent 초기화 중...")
 
        llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            # 【중요】문서 생성은 temperature를 낮춥니다
            # 0.7 → 0.2
            # 이유: 법적 문서는 표현이 일관되고 정확해야 합니다.
            #      창의적으로 쓰면 곤란합니다.
            temperature=0.2,
            api_key=settings.OPENAI_API_KEY,
            max_retries=3,
            timeout=60,
        )
 
        _doc_agent = DocumentAgent(llm)
        logger.info("[C파트] DocumentAgent 준비 완료")
 
    return _doc_agent


class AskRequest(BaseModel):
    """
    【요청】프론트에서 보낼 형식

    {
      "question": "보증금 5천만원을 못 받았어요"
    }
    """
    question: str = Field(
        ...,
        min_length=2,
        max_length=1000,
        description="사용자 질문",
        examples=["보증금 5천만원을 못 받았는데 어떻게 해야 하나요?"],
    )

    conversation_id: Optional[int] = Field(
        None,
        description="대화 ID (개인화용, 아직 미사용)",
    )


class SectionResponse(BaseModel):
    """【응답】답변 섹션 하나. 7개 섹션이 모두 이 형태입니다."""
    title: str = Field(..., description="섹션 제목", examples=["상황 진단"])
    content: str = Field(..., description="섹션 본문")
    citations: list[str] = Field(
        default_factory=list,
        description="인용한 조문·판례",
        examples=[["제3조의2", "2023다202228"]],
    )


class AskResponse(BaseModel):
    """
    【응답】답변 전체
    """
    is_off_topic: bool = Field(
        ...,
        description="카테고리3(보증금·경매·배당) 범위 밖이면 true",
    )

    # 【Off-topic일 때만 채워짐】
    message: Optional[str] = Field(
        None,
        description="off-topic일 때의 안내 메시지",
    )

    # 【정상 답변일 때만 채워짐】7개 섹션
    situation: Optional[SectionResponse] = Field(None, description="상황 진단")
    legal_basis: Optional[SectionResponse] = Field(None, description="관련 법 조문")
    precedents: Optional[SectionResponse] = Field(None, description="관련 판례")
    action_steps: Optional[SectionResponse] = Field(None, description="행동 절차")
    expected_cost: Optional[SectionResponse] = Field(None, description="예상 비용")
    anticipated_disputes: Optional[SectionResponse] = Field(None, description="임대인 반박 대응")
    follow_up_questions: list[str] = Field(
        default_factory=list,
        description="자주 묻는 질문 (Q/A 형식 문자열 리스트)",
    )

    # 【메타 정보】
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="답변 신뢰도. 근거(조문·판례)가 많고 보증금 액수를 알수록 높아집니다.",
    )
    deposit_amount: Optional[int] = Field(
        None,
        description="질문에서 추출한 보증금 액수(원). null이면 비용 계산이 생략된 것입니다.",
    )
    elapsed_seconds: float = Field(..., description="응답 생성 소요 시간(초)")
    generated_at: str = Field(..., description="생성 시각 (ISO 8601)")



class DocumentRequest(BaseModel):
    """
    【요청】문서 생성

    """
    user_message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="사용자 메시지",
        examples=["내용증명 써주세요", "집주인은 김철수이고 보증금은 5천만원이에요"],
    )
 
    collected: dict = Field(
        default_factory=dict,
        description=(
            "지금까지 모은 정보. "
            "첫 요청에는 빈 객체 {}, "
            "이후에는 직전 응답의 collected를 그대로 다시 보내세요."
        ),
    )
 
    # ⚠️ 아직 미사용. conversations 완성되면 이걸로 대체됩니다.
    conversation_id: Optional[int] = Field(
        None,
        description="대화 ID (미사용, conversations repository 완성 후 활성화 예정)",
    )
 
 
class DocumentResponse(BaseModel):
    """
    【응답】문서 생성
 
    """
    status: str = Field(
        ...,
        description="need_more_info(정보 부족) 또는 complete(문서 완성)",
    )
 
    collected: dict = Field(
        ...,
        description="⚠️ 이것을 저장했다가 다음 요청에 그대로 다시 보내세요!",
    )
 
    missing: list[str] = Field(
        default_factory=list,
        description="아직 없는 필드명 (영문)",
    )
 
    missing_labels: list[str] = Field(
        default_factory=list,
        description="아직 없는 항목 (한글, 화면 표시용)",
    )
 
    progress: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="진행률 (0.0~1.0). 프론트 진행바에 사용하세요.",
    )
 
    next_question: Optional[str] = Field(
        None,
        description="다음에 물어볼 질문 (status=need_more_info일 때만)",
    )
 
    document: Optional[str] = Field(
        None,
        description="완성된 내용증명 본문 (status=complete일 때만)",
    )


class DocumentOCRRequest(BaseModel):
    """
    【요청】이미지로 문서 정보 추출

    프론트에서 계약서 사진을 base64로 인코딩해서 보냅니다.
    """
    image_base64: str = Field(
        ...,
        description="base64 인코딩된 이미지 (data:image/... 접두사 포함 가능)",
    )
    image_format: str = Field(
        "jpg",
        description="이미지 형식 (jpg, png, pdf)",
        examples=["jpg", "png", "pdf"],
    )
    collected: dict = Field(
        default_factory=dict,
        description="지금까지 모은 정보 (첫 요청은 빈 객체)",
    )


class DocumentOCRResponse(BaseModel):
    """【응답】이미지 정보 추출 결과"""
    status: str = Field(..., description="need_more_info 또는 complete")
    collected: dict = Field(..., description="⚠️ 저장했다가 다음 요청에 다시 보내세요")
    extracted_from_image: list[str] = Field(
        default_factory=list,
        description="이미지에서 새로 찾은 항목 (사용자에게 '계약서에서 이걸 찾았어요' 표시용)",
    )
    missing: list[str] = Field(default_factory=list)
    missing_labels: list[str] = Field(default_factory=list)
    progress: float = Field(..., ge=0.0, le=1.0)
    next_question: Optional[str] = Field(None)
    document: Optional[str] = Field(None)
 
# ════════════════════════════════════════════════════════════════════════════════
# 【헬퍼】Retriever 결과 → Agent 입력 형식 변환
# ════════════════════════════════════════════════════════════════════════════════

def _convert_search_results(chunks: list) -> dict:
    """
    【변환】list[RetrievedChunk] → {"statutes": [...], "precedents": [...]}

    RetrievedChunk의 source_type 필드로 조문/판례를 구분합니다.
    """
    statutes = []
    precedents = []

    for chunk in chunks:
        # 【조문】
        if chunk.source_type == "statute":
            # 조문번호 조립: statute_number="8" + branch=None → "8조"
            #                statute_number="3" + branch="2"  → "3조의2"
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

        # 【판례】
        elif chunk.source_type == "precedent":
            precedents.append({
                "case_number": chunk.case_number or "",
                "case_name": chunk.case_name or "",
                "case_date": str(chunk.case_date) if chunk.case_date else "",
                "content": chunk.content,
                "similarity": chunk.similarity,
                # ⚠️ court_level, case_year, ruling_type은 DB(legal_documents_c)에
                #    있지만 Retriever가 SELECT를 안 해서 못 가져옵니다.
                #    → 기본값을 넣습니다. 지어내지 않습니다.
                #    → 개선하려면 Retriever의 SQL에 컬럼을 추가해야 합니다.
                "court_level": 0,
                "case_year": "",
                "ruling_type": "",
            })

    return {"statutes": statutes, "precedents": precedents}


# ════════════════════════════════════════════════════════════════════════════════
# 【엔드포인트 1】답변 생성  ← 메인
# ════════════════════════════════════════════════════════════════════════════════

@router.post(
    "/ask",
    response_model=AskResponse,
    summary="보증금 반환 관련 질문에 답변",
    description=(
        "주택임대차 보증금 반환·경매·배당 관련 질문에 답변합니다.\n\n"
        "**⏱️ 소요 시간: 약 30~45초** (GPT를 8회 호출하기 때문입니다)\n\n"
        "카테고리3 범위 밖의 질문이면 `is_off_topic=true`와 안내 메시지만 반환합니다 "
        "(이 경우 3초 이내에 응답합니다)."
    ),
)
async def ask(request: AskRequest) -> AskResponse:
    """
    【메인 엔드포인트】질문 → 답변

    """
    start = time.time()

    try:
        # ────────────────────────────────────────────────────────────────
        # 【1】조문·판례 검색 (DB, GPT 안 씀)
        # ────────────────────────────────────────────────────────────────
        retriever = _get_retriever()
        raw_chunks = retriever.search(request.question)
        search_results = _convert_search_results(raw_chunks)

        logger.info(
            f"[C파트] 검색 완료: 조문 {len(search_results['statutes'])}개, "
            f"판례 {len(search_results['precedents'])}개"
        )

        # ────────────────────────────────────────────────────────────────
        # 【2】그래프 실행 (GPT 호출)
        # ────────────────────────────────────────────────────────────────
        graph = _get_graph()

        result = await graph.ainvoke({
            "question": request.question,
            "search_results": search_results,
            # ⚠️ chat_history는 아직 None입니다.
            #    conversations repository가 완성되면 여기에 이전 대화를 넣습니다 (#19).
            #    지금은 매 질문이 독립적입니다 (맥락 기억 못 함).
            "chat_history": None,
            "user_id": None,
        })

        elapsed = time.time() - start

        # ────────────────────────────────────────────────────────────────
        # 【3】에러 처리
        # ────────────────────────────────────────────────────────────────
        answer = result.get("answer")

        if not answer:
            error_msg = result.get("error", "알 수 없는 오류")
            logger.error(f"[C파트] 답변 생성 실패: {error_msg}")

            raise HTTPException(
                status_code=500,
                detail=f"답변 생성에 실패했습니다: {error_msg}",
            )

        # ────────────────────────────────────────────────────────────────
        # 【4-A】Off-topic → 안내 메시지만 반환
        # ────────────────────────────────────────────────────────────────
        if answer.get("is_off_topic"):
            logger.info(f"[C파트] Off-topic 질문 ({elapsed:.1f}초)")

            return AskResponse(
                is_off_topic=True,
                message=answer.get("message"),
                confidence_score=answer.get("confidence_score", 0.0),
                elapsed_seconds=round(elapsed, 2),
                generated_at=answer.get("generated_at", ""),
            )

        # ────────────────────────────────────────────────────────────────
        # 【4-B】정상 답변 → 7개 섹션 반환
        # ────────────────────────────────────────────────────────────────
        logger.info(
            f"[C파트] 답변 생성 완료 "
            f"(신뢰도 {answer.get('confidence_score', 0):.2f}, {elapsed:.1f}초)"
        )

        def to_section(key: str) -> Optional[SectionResponse]:
            """
            【변환】dict → SectionResponse

            내용이 비어있으면 None을 반환합니다.
            (노드가 실패했을 수 있으므로 방어적으로)
            """
            s = answer.get(key)
            if not s or not s.get("content"):
                return None
            return SectionResponse(
                title=s.get("title", ""),
                content=s.get("content", ""),
                citations=s.get("citations", []),
            )

        return AskResponse(
            is_off_topic=False,
            situation=to_section("situation"),
            legal_basis=to_section("legal_basis"),
            precedents=to_section("precedents"),
            action_steps=to_section("action_steps"),
            expected_cost=to_section("expected_cost"),
            anticipated_disputes=to_section("anticipated_disputes"),
            follow_up_questions=answer.get("follow_up_questions", []),
            confidence_score=answer.get("confidence_score", 0.0),
            deposit_amount=answer.get("deposit_amount"),
            elapsed_seconds=round(elapsed, 2),
            generated_at=answer.get("generated_at", ""),
        )

    except HTTPException:
        # 위에서 명시적으로 던진 것은 그대로 통과시킵니다
        raise

    except Exception as e:
        # 예상하지 못한 오류
        # ⚠️ logger.exception을 쓰면 스택트레이스까지 로그에 남습니다
        logger.exception(f"[C파트] 예외 발생: {e}")
        raise HTTPException(
            status_code=500,
            detail="답변 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
        )

@router.post(
    "/document",
    response_model=DocumentResponse,
    summary="내용증명 생성 (대화형)",
    description=(
        "보증금 반환 청구 내용증명을 대화형으로 작성합니다.\n\n"
        "**동작 방식:**\n"
        "1. 사용자가 메시지를 보냅니다\n"
        "2. 에이전트가 정보를 추출합니다\n"
        "3. 정보가 부족하면 되묻습니다 (`status=need_more_info`)\n"
        "4. 다 모이면 문서를 생성합니다 (`status=complete`)\n\n"
        "**⚠️ 중요:** 응답의 `collected`를 저장했다가 "
        "다음 요청에 그대로 다시 보내야 합니다.\n\n"
        "**소요 시간:** 되묻기 5~8초 / 문서 생성 15~25초"
    ),
)
async def create_document(request: DocumentRequest) -> DocumentResponse:

    try:
        agent = _get_doc_agent()
 
        result = await agent.process(
            user_message=request.user_message,
            collected=request.collected,
        )
 
        logger.info(
            f"[C파트] 문서 생성 {result['status']} "
            f"(진행률 {result['progress']:.0%})"
        )
 
        return DocumentResponse(**result)
 
    except Exception as e:
        logger.exception(f"[C파트] 문서 생성 실패: {e}")
        raise HTTPException(
            status_code=500,
            detail="문서 생성 중 오류가 발생했습니다.",
        )
 
 
@router.get(
    "/document/fields",
    summary="내용증명 필수 항목 조회",
    description=(
        "내용증명 작성에 필요한 항목 목록을 반환합니다.\n\n"
        "프론트에서 '필요한 정보' 체크리스트를 보여줄 때 사용하세요.\n"
        "**GPT를 호출하지 않으므로 즉시 응답합니다.**"
    ),
)
async def get_document_fields():
    """
    【필드 조회】내용증명에 필요한 항목 - 체크리스트
    """
    from app.graph.parts.c_part.agents.document_agent import (
        REQUIRED_FIELDS,
        OPTIONAL_FIELDS,
    )
 
    return {
        "required": [
            {"key": k, "label": v}
            for k, v in REQUIRED_FIELDS.items()
        ],
        "optional": [
            {"key": k, "label": v}
            for k, v in OPTIONAL_FIELDS.items()
        ],
    }

@router.post(
    "/document/ocr",
    response_model=DocumentOCRResponse,
    summary="계약서 이미지로 내용증명 정보 자동 입력",
    description=(
        "임대차계약서 사진을 올리면 클로바 OCR로 텍스트를 추출하고,\n"
        "내용증명에 필요한 정보(임대인 이름, 보증금 등)를 자동으로 채웁니다.\n\n"
        "**사용자 편의 기능:** 6개 항목을 타이핑하는 대신 계약서 한 장으로 대부분 자동 입력.\n\n"
        "이미지에서 못 찾은 항목만 이후 대화로 되묻습니다.\n\n"
        "**소요 시간:** OCR 3~5초 + 정보 추출 3초"
    ),
)
async def create_document_from_image(
    request: DocumentOCRRequest,
) -> DocumentOCRResponse:
    """
    【OCR 문서】계약서 이미지 → 정보 자동 추출
    """
    try:
        agent = _get_doc_agent()

        # 【OCR 사용 가능 확인】
        if not agent.ocr.is_available():
            raise HTTPException(
                status_code=503,
                detail=(
                    "OCR 기능이 현재 설정되지 않았습니다. "
                    "정보를 텍스트로 직접 입력해 주세요 (/document 엔드포인트)."
                ),
            )

        result = await agent.process_image(
            image_base64=request.image_base64,
            image_format=request.image_format,
            collected=request.collected,
        )

        logger.info(
            f"[C파트] OCR 문서 {result['status']} "
            f"(이미지에서 {len(result.get('extracted_from_image', []))}개 추출)"
        )

        return DocumentOCRResponse(**result)

    except HTTPException:
        raise

    except RuntimeError as e:
        # OCR 처리 실패 (이미지 품질 등) → 사용자에게 안내
        logger.error(f"[C파트] OCR 처리 실패: {e}")
        raise HTTPException(status_code=422, detail=str(e))

    except Exception as e:
        logger.exception(f"[C파트] OCR 문서 생성 실패: {e}")
        raise HTTPException(
            status_code=500,
            detail="이미지 처리 중 오류가 발생했습니다.",
        )
# ════════════════════════════════════════════════════════════════════════════════
# 【엔드포인트 2】상태 확인
# ════════════════════════════════════════════════════════════════════════════════

@router.get(
    "/health",
    summary="C파트 상태 확인",
    description="그래프·Retriever·DB가 정상인지 확인합니다. 프론트 연동 테스트용.",
)
async def health():

    status = {
        "graph": False,
        "retriever": False,
        "database": False,
    }

    # 【그래프】
    try:
        _get_graph()
        status["graph"] = True
    except Exception as e:
        logger.error(f"[Health] 그래프 초기화 실패: {e}")

    # 【Retriever】
    try:
        _get_retriever()
        status["retriever"] = True
    except Exception as e:
        logger.error(f"[Health] Retriever 초기화 실패: {e}")

    # 【DB】비용 데이터를 실제로 조회해서 확인
    try:
        repo = _get_cost_repo()
        procedures = repo.get_all_procedures()
        status["database"] = len(procedures) > 0
    except Exception as e:
        logger.error(f"[Health] DB 조회 실패: {e}")

    all_ok = all(status.values())

    return {
        "status": "ok" if all_ok else "degraded",
        "components": status,
    }


# ════════════════════════════════════════════════════════════════════════════════
# 【엔드포인트 3】공식 비용 데이터 조회
# ════════════════════════════════════════════════════════════════════════════════

@router.get(
    "/costs",
    summary="공식 비용 데이터 조회",
    description=(
        "절차별 공식 수수료와 지역별 소액임차인 기준을 반환합니다.\n\n"
        "프론트에서 '비용 안내' 페이지를 만들 때 사용하세요.\n\n"
        "**GPT를 호출하지 않으므로 즉시 응답합니다.**\n\n"
        "`?deposit=50000000`을 붙이면 해당 보증금 기준으로 "
        "인지대·송달료를 계산해서 함께 반환합니다."
    ),
)
async def get_costs(deposit: Optional[int] = None):
    """
    【비용 조회】DB의 공식 데이터 반환
    """
    try:
        repo = _get_cost_repo()

        response = {
            "procedures": repo.get_all_procedures(),
            "region_tiers": repo.get_all_region_tiers(),
        }

        # 【보증금이 주어지면】정확한 금액 계산해서 추가
        if deposit and deposit > 0:
            calculations = {}

            for proc in ["임차권등기명령", "소액사건", "일반소송"]:
                result = repo.calculate_total_cost(deposit, proc)

                # 【자격 판정】소액사건은 소가 3,000만원 이하만 가능
                if proc == "소액사건" and deposit > 30_000_000:
                    result["eligible"] = False
                    result["reason"] = "소가 3,000만원 초과 — 일반소송 대상입니다"
                else:
                    result["eligible"] = True

                calculations[proc] = result

            response["deposit_amount"] = deposit
            response["calculations"] = calculations

        return response

    except Exception as e:
        logger.exception(f"[C파트] 비용 조회 실패: {e}")
        raise HTTPException(
            status_code=500,
            detail="비용 데이터를 불러오지 못했습니다.",
        )