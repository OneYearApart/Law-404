"""
【FastAPI 라우터】C파트 - 보증금 반환·경매·배당

"""
import asyncio
import logging
import time
from typing import Optional, AsyncIterator

from fastapi.responses import StreamingResponse
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from app.graph.parts.c_part.builder import get_c_part_graph
from app.graph.parts.c_part.agents.document_agent import (
    DocumentAgent,
    REQUIRED_FIELDS,
    OPTIONAL_FIELDS,
)
from app.rag.retrievers.c_part import CPartRetriever
from app.rag.repositories.cost_repository import CostRepository
from langchain_openai import ChatOpenAI
from app.core.config import settings

# 【인증】로그인 필수 — 비로그인이면 get_current_user가 401
from app.auth.dependencies import get_current_user
from app.auth.orm import User
from app.api.sse import sse_event, sse_comment

# 【대화 저장】conversations repository
from app.conversations import repository as conv_repo

from sse import sse_event, sse_comment 
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/c-part", tags=["C파트 - 보증금 반환"])

# 【파트 식별자】이 라우터는 항상 "c"
PART = "c"


# ════════════════════════════════════════════════════════════════════════════════
# 【싱글턴】무거운 객체는 한 번만 생성
# ════════════════════════════════════════════════════════════════════════════════

_graph = None
_retriever = None
_cost_repo = None
_doc_agent = None
_definition_llm = None


def _get_graph():
    global _graph
    if _graph is None:
        logger.info("[C파트] 그래프 초기화 중...")
        _graph = get_c_part_graph()
        logger.info("[C파트] 그래프 준비 완료")
    return _graph


def _get_retriever():
    global _retriever
    if _retriever is None:
        _retriever = CPartRetriever()
    return _retriever


def _get_cost_repo():
    global _cost_repo
    if _cost_repo is None:
        _cost_repo = CostRepository()
    return _cost_repo


def _get_doc_agent():
    """
    【싱글턴】DocumentAgent

    ⚠️ 상담용 LLM(temperature=0.7)과 별도.
       문서 생성은 정확성이 중요하므로 temperature=0.2.
    """
    global _doc_agent
    if _doc_agent is None:
        logger.info("[C파트] DocumentAgent 초기화 중...")
        llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            temperature=0.2,
            api_key=settings.OPENAI_API_KEY,   # ⚠️ 대문자 (config.py 필드명)
            max_retries=3,
            timeout=60,
        )
        _doc_agent = DocumentAgent(llm)
        logger.info("[C파트] DocumentAgent 준비 완료")
    return _doc_agent


def _get_definition_llm():
    """
    【싱글턴】정의 답변용 LLM

    ⚠️ DEFINITION 전용. 용어 설명만 하는 가벼운 호출.
       상담 그래프(8노드)를 안 거치고 이 LLM으로 1회만 호출.
    """
    global _definition_llm
    if _definition_llm is None:
        _definition_llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            temperature=0.3,
            api_key=settings.OPENAI_API_KEY,
            max_retries=3,
            timeout=30,
        )
    return _definition_llm


# ════════════════════════════════════════════════════════════════════════════════
# 【스키마】
# ════════════════════════════════════════════════════════════════════════════════

class CreateConversationResponse(BaseModel):
    """【응답】새 대화 생성"""
    conversation_id: int = Field(..., description="생성된 대화 ID. 이후 요청에 사용하세요.")


class AskRequest(BaseModel):
    """【요청】상담 질문"""
    question: str = Field(..., min_length=2, max_length=1000,
                          examples=["보증금 5천만원을 못 받았는데 어떻게 해야 하나요?"])
    conversation_id: int = Field(..., description="대화 ID (먼저 /conversations로 생성)")


class SectionResponse(BaseModel):
    title: str
    content: str
    citations: list[str] = Field(default_factory=list)


class AskResponse(BaseModel):
    """
    【응답】상담 답변

    ⚠️ 3가지 경우:
    - response_type="definition"   → 용어 정의 (message만)
    - response_type="off_topic"    → 범위 밖 (message만)
    - response_type="consultation" → 정식 상담 (7개 섹션)
    """
    response_type: str = Field(..., description="definition | off_topic | consultation")

    # 【definition / off_topic】
    message: Optional[str] = Field(None)

    # 【consultation】7개 섹션
    situation: Optional[SectionResponse] = None
    legal_basis: Optional[SectionResponse] = None
    precedents: Optional[SectionResponse] = None
    action_steps: Optional[SectionResponse] = None
    expected_cost: Optional[SectionResponse] = None
    anticipated_disputes: Optional[SectionResponse] = None
    follow_up_questions: list[str] = Field(default_factory=list)

    # 【메타】
    confidence_score: float = Field(0.0, ge=0.0, le=1.0)
    deposit_amount: Optional[int] = None
    elapsed_seconds: float = 0.0
    conversation_id: int


class DocumentRequest(BaseModel):
    """
    【요청】문서 생성 (대화형)

    ⚠️ collected를 프론트가 안 들고 다녀도 됩니다!
       conversation_id로 서버가 state에 저장/조회합니다.
    """
    user_message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: int = Field(..., description="대화 ID")


class DocumentResponse(BaseModel):
    status: str = Field(..., description="need_more_info | complete")
    missing_labels: list[str] = Field(default_factory=list)
    progress: float = Field(..., ge=0.0, le=1.0)
    next_question: Optional[str] = None
    document: Optional[str] = None
    conversation_id: int


class DocumentOCRRequest(BaseModel):
    """【요청】이미지로 문서 정보 추출"""
    image_base64: str = Field(..., description="base64 인코딩 이미지")
    image_format: str = Field("jpg", examples=["jpg", "png", "pdf"])
    conversation_id: int = Field(..., description="대화 ID")


class DocumentOCRResponse(BaseModel):
    status: str
    extracted_from_image: list[str] = Field(default_factory=list)
    missing_labels: list[str] = Field(default_factory=list)
    progress: float = Field(..., ge=0.0, le=1.0)
    next_question: Optional[str] = None
    document: Optional[str] = None
    conversation_id: int


# ════════════════════════════════════════════════════════════════════════════════
# 【헬퍼】검색 결과 변환
# ════════════════════════════════════════════════════════════════════════════════

def _convert_search_results(chunks: list) -> dict:
    """list[RetrievedChunk] → {"statutes": [...], "precedents": [...]}"""
    statutes, precedents = [], []
    for chunk in chunks:
        if chunk.source_type == "statute":
            article_num = chunk.statute_number or ""
            article_num = (f"{article_num}조의{chunk.statute_branch}"
                           if chunk.statute_branch else f"{article_num}조")
            statutes.append({
                "article_number": article_num,
                "title": chunk.statute_title or "",
                "content": chunk.content,
                "similarity": chunk.similarity,
            })
        elif chunk.source_type == "precedent":
            precedents.append({
                "case_number": chunk.case_number or "",
                "case_name": chunk.case_name or "",
                "case_date": str(chunk.case_date) if chunk.case_date else "",
                "content": chunk.content,
                "similarity": chunk.similarity,
                "court_level": 0, "case_year": "", "ruling_type": "",
            })
    return {"statutes": statutes, "precedents": precedents}


async def _load_chat_history(conversation_id: int, user_id: int) -> Optional[list]:
    """
    【대화 히스토리 로드】이전 메시지를 그래프용 형식으로

    ⚠️ 전부 넣으면 토큰이 폭증하므로 최근 6개(3턴)만.
       Message(role, content) → [{"role": ..., "content": ...}]
    """
    try:
        messages = await conv_repo.load_conversation(conversation_id, user_id)
    except Exception as e:
        # 대화가 없거나 접근 불가 → 히스토리 없이 진행 (신규 대화일 수 있음)
        logger.info(f"[C파트] 히스토리 로드 스킵: {type(e).__name__}")
        return None

    if not messages:
        return None

    # 최근 6개만 (3턴). 시간순 정렬은 load_conversation이 이미 함.
    recent = messages[-6:]
    return [{"role": m.role, "content": m.content} for m in recent]


# ════════════════════════════════════════════════════════════════════════════════
# 【엔드포인트 0】대화 생성
# ════════════════════════════════════════════════════════════════════════════════

@router.post(
    "/conversations",
    response_model=CreateConversationResponse,
    summary="새 대화 시작",
    description="C파트 대화를 새로 만들고 conversation_id를 반환합니다. "
                "이후 /ask, /document 요청에 이 ID를 사용하세요.",
)
async def create_conversation(
    user: User = Depends(get_current_user),
):
    """
    【대화 생성】

    프론트에서 "새 상담" 또는 "새 문서 작성" 시작 시 호출합니다.
    반환된 conversation_id를 이후 모든 요청에 넣으세요.
    """
    try:
        conv = await conv_repo.create_conversation(user_id=user.id, part=PART)
        logger.info(f"[C파트] 대화 생성: id={conv.id}, user={user.id}")
        return CreateConversationResponse(conversation_id=conv.id)

    except Exception as e:
        logger.exception(f"[C파트] 대화 생성 실패: {e}")
        raise HTTPException(500, "대화를 생성하지 못했습니다.")


# ════════════════════════════════════════════════════════════════════════════════
# 【엔드포인트 1】상담 (DEFINITION 분기 포함)
# ════════════════════════════════════════════════════════════════════════════════

@router.post(
    "/ask",
    response_model=AskResponse,
    summary="보증금 반환 상담",
    description=(
        "질문 유형에 따라 다르게 처리합니다:\n"
        "- **용어 정의** ('내용증명이 뭐예요?') → 간단히 정의만 (5초)\n"
        "- **범위 밖** → 안내 메시지\n"
        "- **정식 상담** → 7개 섹션 전체 (40초)"
    ),
)
async def ask(
    request: AskRequest,
    user: User = Depends(get_current_user),
) -> AskResponse:
    """
    【상담】intent에 따라 분기

    흐름:
      1. 이전 대화 로드
      2. Classifier로 intent 판단
         - definition   → 정의만 (LLM 1회)
         - irrelevant   → 안내
         - consultation → 상담 그래프 (8노드)
         - document     → "문서 모드로 전환하세요" 안내
      3. 대화 저장
    """
    start = time.time()
    conv_id = request.conversation_id

    try:
        # 【1】이전 대화 로드
        chat_history = await _load_chat_history(conv_id, user.id)

        # 【2】검색
        retriever = _get_retriever()
        raw = retriever.search(request.question)
        search_results = _convert_search_results(raw)

        # 【3】그래프 실행
        graph = _get_graph()
        result = await graph.ainvoke({
            "question": request.question,
            "search_results": search_results,
            "chat_history": chat_history,
            "user_id": user.id,
        })

        elapsed = time.time() - start
        answer = result.get("answer")

        if not answer:
            raise HTTPException(500, f"답변 생성 실패: {result.get('error')}")

        # 【4】사용자 질문 저장 (답변 종류와 무관하게)
        await conv_repo.save_message(user.id, PART, "user", request.question, conv_id)

        # ── 분기 A: 정의 답변 (그래프가 definition으로 처리한 경우) ──
        # ⚠️ classify_topic이 intent=definition을 반환하면,
        #    그래프의 classifier 노드가 answer에 is_definition을 세팅합니다.
        #    (아래 graph.py 수정 참고)
        if answer.get("is_definition"):
            msg = answer.get("message", "")
            await conv_repo.save_message(user.id, PART, "assistant", msg, conv_id)
            return AskResponse(
                response_type="definition",
                message=msg,
                confidence_score=answer.get("confidence_score", 0.9),
                elapsed_seconds=round(elapsed, 2),
                conversation_id=conv_id,
            )

        # ── 분기 B: off-topic ──
        if answer.get("is_off_topic"):
            msg = answer.get("message", "")
            await conv_repo.save_message(user.id, PART, "assistant", msg, conv_id)
            return AskResponse(
                response_type="off_topic",
                message=msg,
                confidence_score=answer.get("confidence_score", 0.0),
                elapsed_seconds=round(elapsed, 2),
                conversation_id=conv_id,
            )

        # ── 분기 C: 정식 상담 (7개 섹션) ──
        def to_section(key):
            s = answer.get(key)
            if not s or not s.get("content"):
                return None
            return SectionResponse(
                title=s.get("title", ""),
                content=s.get("content", ""),
                citations=s.get("citations", []),
            )

        # 【답변 저장】섹션들을 하나의 텍스트로 합쳐서 저장
        # (사이드바/히스토리 표시용. 구조화 원본은 프론트가 이미 받음)
        saved_text = _assemble_answer_text(answer)
        await conv_repo.save_message(user.id, PART, "assistant", saved_text, conv_id)

        logger.info(f"[C파트] 상담 완료 (신뢰도 {answer.get('confidence_score', 0):.2f}, "
                    f"{elapsed:.1f}초)")

        return AskResponse(
            response_type="consultation",
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
            conversation_id=conv_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[C파트] 상담 실패: {e}")
        raise HTTPException(500, "답변 생성 중 오류가 발생했습니다.")


def _assemble_answer_text(answer: dict) -> str:
    """
    【헬퍼】구조화된 답변 → 저장용 단일 텍스트

    히스토리에 저장할 때는 하나의 문자열로 합칩니다.
    (다음 턴에 chat_history로 로드될 때 읽기 좋게)
    """
    parts = []
    for key in ["situation", "legal_basis", "action_steps", "expected_cost"]:
        s = answer.get(key, {})
        if s.get("content"):
            parts.append(f"[{s.get('title', key)}]\n{s['content']}")
    return "\n\n".join(parts)


# ════════════════════════════════════════════════════════════════════════════
# 【섹션 키 매핑】그래프 노드 반환 필드명 → 프론트 섹션 key
# ════════════════════════════════════════════════════════════════════════════
# graph.py 의 각 노드는 아래 필드명으로 반환합니다.
# updates 모드는 {"노드명": {"필드명": {...}}} 형태로 방출되므로,
# 노드명이 아니라 "그 안의 필드"를 봐야 합니다.
 
SECTION_FIELDS = {
    "situation_section": "situation",
    "legal_basis_section": "legal_basis",
    "precedents_section": "precedents",
    "action_steps_section": "action_steps",
    "expected_cost_section": "expected_cost",
    "anticipated_disputes_section": "anticipated_disputes",
}
 
# 이 순서대로 프론트가 자리를 미리 잡아둡니다 (도착은 병렬로 뒤섞여도 무방).
SECTION_ORDER = [
    "situation", "legal_basis", "precedents",
    "action_steps", "expected_cost", "anticipated_disputes",
]
 
 
async def _stream_ask(
    question: str,
    conv_id: int,
    user_id: int,
) -> AsyncIterator[str]:
    """
    【SSE 제너레이터】그래프를 astream 으로 돌리며 이벤트를 흘려보낸다.
 
    구조는 기존 JSON /ask 와 동일:
      1) 히스토리 로드 → 2) 검색 → 3) 그래프 실행 → 4) 저장
    다만 3)을 ainvoke 대신 astream 으로 바꿔 노드별로 방출.
    """
    start = time.time()
 
    # 방출된 섹션/faq/메타를 모아두었다가, 마지막에 히스토리 저장에 사용
    collected_sections: dict[str, dict] = {}
    follow_up: list[str] = []
    meta_emitted = False
 
    try:
        # 【1】이전 대화 로드
        chat_history = await _load_chat_history(conv_id, user_id)  # noqa: F821
 
        # 【2】검색 (동기 retriever → 스트림 시작 전에 1회)
        retriever = _get_retriever()  # noqa: F821
        raw = retriever.search(question)
        search_results = _convert_search_results(raw)  # noqa: F821
 
        # 【사용자 질문 저장】답변 종류와 무관하게 먼저 기록
        await conv_repo.save_message(user_id, PART, "user", question, conv_id)  # noqa: F821
 
        # 【3】그래프 스트리밍 실행
        graph = _get_graph()  # noqa: F821
 
        classified_sent = False
 
        async for update in graph.astream(
            {
                "question": question,
                "search_results": search_results,
                "chat_history": chat_history,
                "user_id": user_id,
            },
            stream_mode="updates",
        ):
            # update 예시: {"classifier": {"classifier_result": {...}, "answer": {...}}}
            #              {"situation": {"situation_section": {...}}}
            for node_name, node_out in update.items():
                if not isinstance(node_out, dict):
                    continue
 
                # ── 에러 노드 ──
                if node_out.get("error"):
                    yield sse_event("error", {"message": node_out["error"]})
                    return
 
                # ── classifier 노드: 3분기 판정 ──
                if node_name == "classifier":
                    answer = node_out.get("answer")
 
                    # definition / off_topic 은 classifier 가 answer 를 바로 채움
                    if answer and answer.get("is_definition"):
                        yield sse_event("classified", {"response_type": "definition"})
                        msg = answer.get("message", "")
                        yield sse_event("message", {"text": msg})
                        await conv_repo.save_message(user_id, PART, "assistant", msg, conv_id)  # noqa: F821
                        yield sse_event("meta", {
                            "confidence_score": answer.get("confidence_score", 0.9),
                            "deposit_amount": node_out.get("deposit_amount"),
                            "elapsed_seconds": round(time.time() - start, 2),
                        })
                        yield sse_event("done", {"conversation_id": conv_id})
                        return
 
                    if answer and answer.get("is_off_topic"):
                        yield sse_event("classified", {"response_type": "off_topic"})
                        msg = answer.get("message", "")
                        yield sse_event("message", {"text": msg})
                        await conv_repo.save_message(user_id, PART, "assistant", msg, conv_id)  # noqa: F821
                        yield sse_event("meta", {
                            "confidence_score": answer.get("confidence_score", 0.0),
                            "deposit_amount": None,
                            "elapsed_seconds": round(time.time() - start, 2),
                        })
                        yield sse_event("done", {"conversation_id": conv_id})
                        return
 
                    # 정상 상담 진입
                    if not classified_sent:
                        yield sse_event("classified", {"response_type": "consultation"})
                        classified_sent = True
                        # 섹션이 채워질 자리를 프론트가 미리 그리도록 순서 힌트 전달
                        yield sse_event("outline", {"sections": SECTION_ORDER})
                    continue
 
                # ── 섹션 노드들 ──
                emitted_section = False
                for field, key in SECTION_FIELDS.items():
                    if field in node_out and node_out[field]:
                        section = node_out[field]
                        collected_sections[key] = section
                        yield sse_event("section", {
                            "key": key,
                            "title": section.get("title", ""),
                            "content": section.get("content", ""),
                            "citations": section.get("citations", []),
                        })
                        emitted_section = True
 
                # ── FAQ 노드 ──
                if "follow_up_questions" in node_out and node_out["follow_up_questions"] is not None:
                    follow_up = node_out["follow_up_questions"]
                    yield sse_event("faq", {"follow_up_questions": follow_up})
                    emitted_section = True
 
                # keep-alive: 병렬 노드 대기 중 프록시 타임아웃 방지
                if emitted_section:
                    yield sse_comment("ping")
 
        # 【4】정상 상담 종료 처리 — 메타 + 히스토리 저장
        # assemble 노드가 최종 answer 를 만들지만, 우리는 섹션을 이미 다 보냈으므로
        # 메타 정보만 마지막에 전달한다.
        elapsed = round(time.time() - start, 2)
 
        # 저장용 텍스트 (사이드바 히스토리 표시용)
        saved_text = _assemble_answer_text({  # noqa: F821
            **collected_sections,
        })
        if saved_text:
            await conv_repo.save_message(user_id, PART, "assistant", saved_text, conv_id)  # noqa: F821
 
        if not meta_emitted:
            yield sse_event("meta", {
                "confidence_score": _confidence_from_sections(collected_sections, search_results),
                "deposit_amount": None,  # 필요 시 그래프 state 에서 뽑아 전달 가능
                "elapsed_seconds": elapsed,
            })
 
        yield sse_event("done", {"conversation_id": conv_id})
        logger.info(f"[C파트/stream] 상담 완료 ({elapsed:.1f}초)")
 
    except asyncio.CancelledError:
        # 클라이언트가 연결을 끊음 (탭 닫기 등) — 조용히 종료
        logger.info("[C파트/stream] 클라이언트 연결 종료")
        raise
    except Exception as e:
        logger.exception(f"[C파트/stream] 실패: {e}")
        yield sse_event("error", {"message": "답변 생성 중 오류가 발생했습니다."})
 
 
def _confidence_from_sections(sections: dict, search_results: dict) -> float:
    """
    간이 신뢰도: 근거(조문/판례) 개수와 채워진 섹션 수 기반.
    (원래 assemble 노드가 계산하던 값을 스트림에서는 근사)
    """
    n_stat = len(search_results.get("statutes", []))
    n_prec = len(search_results.get("precedents", []))
    n_sec = sum(1 for s in sections.values() if s.get("content"))
    base = min(1.0, (n_stat + n_prec) / 8.0)
    coverage = n_sec / 6.0
    return round(0.5 * base + 0.5 * coverage, 2)
 
 
# ════════════════════════════════════════════════════════════════════════════
# 【엔드포인트】POST /api/c-part/ask/stream
# ════════════════════════════════════════════════════════════════════════════
# 기존 router 객체에 그대로 붙입니다.
 
@router.post(  # noqa: F821
    "/ask/stream",
    summary="보증금 반환 상담 (SSE 스트리밍)",
    description=(
        "기존 /ask 와 동일한 판정을 하되, 결과를 SSE로 흘려보냅니다.\n"
        "- 섹션이 완성될 때마다 event: section 으로 하나씩 전송\n"
        "- definition/off_topic 은 event: message 로 즉시 종료\n"
        "프론트는 EventSource 가 아니라 fetch + ReadableStream 으로 받으세요 "
        "(POST + Authorization 헤더가 필요하므로)."
    ),
)
async def ask_stream(
    request: AskRequest,  # noqa: F821
    user: "User" = Depends(get_current_user),  # noqa: F821
):
    """
    ⚠️ EventSource 는 GET·쿠키만 지원하므로 쓰지 않습니다.
       이 API 는 POST 바디 + Bearer 인증이라, 프론트는 fetch 스트림으로 읽습니다.
    """
    conv_id = request.conversation_id
 
    # 대화 존재/소유 확인은 저장 시점에 걸러지지만, 스트림 시작 전에 빠르게 검증하면
    # 에러를 200 스트림 안이 아니라 HTTP 4xx 로 돌려줄 수 있어 프론트 처리가 쉽다.
    # (여기서는 최소한으로: 실제 검증 로직이 있으면 호출)
 
    headers = {
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",  # nginx 버퍼링 비활성 (즉시 전송 보장)
    }
 
    return StreamingResponse(
        _stream_ask(request.question, conv_id, user.id),
        media_type="text/event-stream",
        headers=headers,
    )


# ════════════════════════════════════════════════════════════════════════════════
# 【엔드포인트 2】문서 생성 (텍스트)
# ════════════════════════════════════════════════════════════════════════════════

@router.post(
    "/document",
    response_model=DocumentResponse,
    summary="내용증명 생성 (대화형)",
    description="정보를 대화로 모아 내용증명을 작성합니다. "
                "collected는 서버가 conversations.state에 저장하므로 "
                "프론트는 conversation_id만 주고받으면 됩니다.",
)
async def create_document(
    request: DocumentRequest,
    user: User = Depends(get_current_user),
) -> DocumentResponse:
    """
    【문서 생성】state 기반

    흐름:
      1. get_session_state()로 기존 collected 로드
      2. DocumentAgent.process()
      3. update_session_state()로 collected 저장
    """
    conv_id = request.conversation_id

    try:
        agent = _get_doc_agent()

        # 【1】기존 collected 로드 (state에서)
        state = await conv_repo.get_session_state(conv_id, user.id)
        collected = (state or {}).get("collected", {})

        # 【2】처리
        result = await agent.process(
            user_message=request.user_message,
            collected=collected,
        )

        # 【3】갱신된 collected 저장
        # ⚠️ update_session_state는 통째로 덮어씀 → 전체 state를 넘김
        new_state = dict(state or {})
        new_state["collected"] = result["collected"]
        await conv_repo.update_session_state(conv_id, user.id, new_state)

        # 【4】대화 저장
        await conv_repo.save_message(user.id, PART, "user", request.user_message, conv_id)
        assistant_msg = result.get("next_question") or result.get("document") or ""
        if assistant_msg:
            await conv_repo.save_message(user.id, PART, "assistant", assistant_msg, conv_id)

        logger.info(f"[C파트] 문서 {result['status']} (진행률 {result['progress']:.0%})")

        return DocumentResponse(
            status=result["status"],
            missing_labels=result["missing_labels"],
            progress=result["progress"],
            next_question=result["next_question"],
            document=result["document"],
            conversation_id=conv_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[C파트] 문서 생성 실패: {e}")
        raise HTTPException(500, "문서 생성 중 오류가 발생했습니다.")


# ════════════════════════════════════════════════════════════════════════════════
# 【엔드포인트 3】문서 생성 (이미지 OCR)
# ════════════════════════════════════════════════════════════════════════════════

@router.post(
    "/document/ocr",
    response_model=DocumentOCRResponse,
    summary="계약서 이미지로 내용증명 정보 자동 입력",
    description="임대차계약서 사진에서 정보를 자동 추출합니다. "
                "못 찾은 항목만 이후 대화로 되묻습니다.",
)
async def create_document_from_image(
    request: DocumentOCRRequest,
    user: User = Depends(get_current_user),
) -> DocumentOCRResponse:
    """【OCR 문서】이미지 → 정보 추출 → state 저장"""
    conv_id = request.conversation_id

    try:
        agent = _get_doc_agent()

        if not agent.ocr.is_available():
            raise HTTPException(503, "OCR 기능이 설정되지 않았습니다. "
                                     "텍스트로 직접 입력해 주세요.")

        # 【1】기존 collected 로드
        state = await conv_repo.get_session_state(conv_id, user.id)
        collected = (state or {}).get("collected", {})

        # 【2】이미지 처리
        result = await agent.process_image(
            image_base64=request.image_base64,
            image_format=request.image_format,
            collected=collected,
        )

        # 【3】collected 저장
        new_state = dict(state or {})
        new_state["collected"] = result["collected"]
        await conv_repo.update_session_state(conv_id, user.id, new_state)

        # 【4】대화 저장 (이미지 업로드 사실만 기록, 이미지 자체는 저장 안 함)
        found = result.get("extracted_from_image", [])
        user_note = f"[계약서 이미지 업로드 — {len(found)}개 항목 추출]"
        await conv_repo.save_message(user.id, PART, "user", user_note, conv_id)
        assistant_msg = result.get("next_question") or result.get("document") or ""
        if assistant_msg:
            await conv_repo.save_message(user.id, PART, "assistant", assistant_msg, conv_id)

        logger.info(f"[C파트] OCR 문서 {result['status']} "
                    f"(이미지에서 {len(found)}개 추출)")

        return DocumentOCRResponse(
            status=result["status"],
            extracted_from_image=found,
            missing_labels=result["missing_labels"],
            progress=result["progress"],
            next_question=result["next_question"],
            document=result["document"],
            conversation_id=conv_id,
        )

    except HTTPException:
        raise
    except RuntimeError as e:
        logger.error(f"[C파트] OCR 처리 실패: {e}")
        raise HTTPException(422, str(e))
    except Exception as e:
        logger.exception(f"[C파트] OCR 문서 실패: {e}")
        raise HTTPException(500, "이미지 처리 중 오류가 발생했습니다.")


# ════════════════════════════════════════════════════════════════════════════════
# 【엔드포인트 4】비용 조회 (GPT 없음, 인증만)
# ════════════════════════════════════════════════════════════════════════════════

@router.get(
    "/costs",
    summary="공식 비용 데이터 조회",
    description="절차별 수수료 + 지역별 기준. ?deposit=50000000 으로 계산도 가능.",
)
async def get_costs(
    deposit: Optional[int] = None,
    user: User = Depends(get_current_user),
):
    """【비용 조회】GPT 미사용, 즉시 응답"""
    try:
        repo = _get_cost_repo()
        response = {
            "procedures": repo.get_all_procedures(),
            "region_tiers": repo.get_all_region_tiers(),
        }
        if deposit and deposit > 0:
            calcs = {}
            for proc in ["임차권등기명령", "소액사건", "일반소송"]:
                r = repo.calculate_total_cost(deposit, proc)
                if proc == "소액사건" and deposit > 30_000_000:
                    r["eligible"] = False
                    r["reason"] = "소가 3,000만원 초과 — 일반소송 대상"
                else:
                    r["eligible"] = True
                calcs[proc] = r
            response["deposit_amount"] = deposit
            response["calculations"] = calcs
        return response
    except Exception as e:
        logger.exception(f"[C파트] 비용 조회 실패: {e}")
        raise HTTPException(500, "비용 데이터를 불러오지 못했습니다.")


# ════════════════════════════════════════════════════════════════════════════════
# 【엔드포인트 5】상태 확인 (인증 불필요)
# ════════════════════════════════════════════════════════════════════════════════

@router.get("/health", summary="상태 확인")
async def health():
    """【헬스체크】GPT 미사용. 인증도 불필요 (모니터링용)."""
    status = {"graph": False, "retriever": False, "database": False}
    try:
        _get_graph(); status["graph"] = True
    except Exception: pass
    try:
        _get_retriever(); status["retriever"] = True
    except Exception: pass
    try:
        repo = _get_cost_repo()
        status["database"] = len(repo.get_all_procedures()) > 0
    except Exception: pass
    return {"status": "ok" if all(status.values()) else "degraded", "components": status}