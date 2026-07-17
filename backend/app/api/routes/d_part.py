"""
D파트 채팅 엔드포인트.
StreamingResponse로 응답하며, 인증된 사용자만 이용 가능하고 대화 이력을 항상 저장합니다.
d파트 담당자만 이 파일을 수정합니다.
"""
import logging

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth.dependencies import get_current_user
from app.api.events import StreamEvent, EventType
from app.core.config import settings
from app.conversations.repository import get_session_state, save_message, update_session_state
from app.conversations.summarizer import maybe_summarize_conversation
from app.graph.parts.d_part.graph import graph as d_graph
from app.graph.parts.d_part.nodes._context import build_citation_cards, match_glossary_terms
from app.graph.parts.d_part.schemas import DPartAnswerSnapshot, DPartSessionState
from app.rag.retrievers.d_part import DPartRetriever

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat/d", tags=["d_part"])

# 용어사전 조회 전용 — 사전은 프로세스당 1회만 읽고 캐시된다(load_glossary 참고).
_retriever = DPartRetriever()

_ERROR_MESSAGE = "일시적인 오류로 응답을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."


class DPartChatRequest(BaseModel):
    conversation_id: int
    user_input: str


@router.post("/")
async def chat_d(
    request: DPartChatRequest, background_tasks: BackgroundTasks, user=Depends(get_current_user)
):
    # 소유권 검증은 스트리밍 시작 전에. get_session_state가 타인/미존재 대화방이면
    # ConversationNotFoundError를 던지고, StreamingResponse가 만들어지기 전이므로 404가 정상 반환된다.
    conversation_id = request.conversation_id
    raw_state = await get_session_state(conversation_id, user.id)
    session_state = DPartSessionState.model_validate(raw_state) if raw_state else DPartSessionState()

    async def event_generator():
        yield f"data: {StreamEvent(type=EventType.LOADING).model_dump_json()}\n\n"

        try:
            # turn_history는 복원용 누적 이력이라 그래프에 넣지 않는다 — 그래프는 carryover 상태만 본다.
            graph_input = {
                name: getattr(session_state, name)
                for name in DPartSessionState.model_fields
                if name != "turn_history"
            } | request.model_dump()

            await save_message(user.id, "d", "user", request.user_input, conversation_id)

            # 판단 단계(전/중/후, 위험신호 감지 등)는 내부적으로 동기 실행
            final_state = await d_graph.ainvoke(graph_input)

            # 근거 카드(조문/판례 verbatim)를 토큰 스트림 앞에 먼저 내보낸다(B파트 META 패턴, 단위 46).
            # retrieved_chunks가 없는 경로(스테이지 확인질문/special_cases/fallback/근거없음)는 emit 안 함.
            meta: dict = {}
            cards = build_citation_cards(final_state.get("retrieved_chunks", []))
            if cards:
                meta["citations"] = cards

            # 판정은 이번 턴에 새로 확정됐을 때만 싣는다 — victim_judgment는 carryover라
            # 그대로 내보내면 판정 이후 모든 턴에 재부착된다. needs_response_assembly가
            # "이번 턴에 새로 확정했는지" 플래그(support_appendix/response_assembly와 동일 게이트).
            # 지원대상 제외 경로는 victim_judgment가 None이라 자연히 빠진다.
            if final_state.get("needs_response_assembly") and final_state.get("victim_judgment"):
                meta["judgment"] = final_state["victim_judgment"].value

            # 답변 성격을 함께 알린다. 경로마다 같은 두 단계(해설/상황적용)를 쓰지만 내용이
            # 달라(판정 유무·상황 정보 유무) 클라이언트가 제목을 맞추려면 이 값이 필요하다.
            # 응답을 만든 노드가 세팅한 값을 그대로 전달한다 — 여기서 재역산하지 않는다.
            # 확인질문/fallback처럼 응답을 생성하지 않은 턴은 없으므로 자연히 빠진다.
            if final_state.get("answer_kind"):
                meta["answer_kind"] = final_state["answer_kind"]

            if meta:
                yield f"data: {StreamEvent(type=EventType.META, data=meta).model_dump_json()}\n\n"

            # 최종 답변만 토큰 단위로 스트리밍. response_assembly가 조립한 응답은 final_answer를
            # 일부러 비워두므로(ainvoke() 반환 dict는 노드가 사후에 채운 값을 반영 못 함) 여기서
            # 청크를 직접 모아 메시지 저장용 전체 텍스트를 만든다.
            chunks = []
            async for chunk in final_state["response_stream"]:
                chunks.append(chunk)
                yield f"data: {StreamEvent(type=EventType.TOKEN, data=chunk).model_dump_json()}\n\n"

            # 액션플랜·면책은 코드가 만든 결정론 텍스트라 평문에 섞지 않고 구조화해서 내보낸다
            # (클라이언트가 별도 UI 블록으로 렌더). 본문 스트림이 끝난 뒤 보내 읽기 순서를 지킨다.
            tail = {
                key: value
                for key, value in (
                    ("appendix", final_state.get("appendix_text")),
                    ("disclaimer", final_state.get("disclaimer_text")),
                )
                if value
            }

            # 용어 풀이는 답변에 실제로 등장한 용어만 — 본문과 대응(액션플랜)을 함께 훑는다.
            # 우선매수권·조세채권 안분 같은 난해한 용어는 오히려 대응 쪽에 몰려 있다.
            #
            # 단 실제 답변을 생성한 턴(answer_kind)에만 붙인다. 요건을 되묻는 턴은 질문 한 줄이
            # 전부인데 그 문구에도 '대항력' 같은 용어가 들어 있어(구제수단 확인질문), 질문 밑에
            # 용어 카드가 줄줄이 달리는 노이즈가 된다.
            body_text = "".join(chunks)
            if final_state.get("answer_kind"):
                terms = match_glossary_terms(
                    f"{body_text}\n{tail.get('appendix', '')}", await _retriever.load_glossary()
                )
                if terms:
                    tail["terms"] = terms

            if tail:
                yield f"data: {StreamEvent(type=EventType.META, data=tail).model_dump_json()}\n\n"

            # 저장 텍스트는 사용자가 보는 것과 같아야 한다 — 구조화해 내보낸 블록도 이어붙인다.
            # 고정 텍스트 경로(final_answer 세팅됨)는 면책이 이미 인라인돼 있어 그대로 쓴다.
            # terms는 예외로 저장하지 않는다 — 본문에서 파생된 읽기 보조 정보이지 저자가 쓴
            # 내용이 아니고, 저장된 본문만 있으면 언제든 같은 결과로 재도출된다.
            final_answer = final_state.get("final_answer") or "\n\n".join(
                part for part in [body_text, tail.get("appendix"), tail.get("disclaimer")] if part
            )

            # 사이드바 재열람용 완성 답변 스냅샷 — 스트림으로 내보낸 것과 같은 조각을 그대로 보존해
            # 복원 시 라이브 턴과 동일하게 렌더한다. terms는 저장 텍스트와 달리 여기선 보존한다
            # (복원은 본문 재파싱이 아니라 저장된 구조를 그대로 쓰므로).
            snapshot = DPartAnswerSnapshot(
                user_input=request.user_input,
                text=body_text,
                citations=meta.get("citations", []),
                judgment=meta.get("judgment"),
                appendix=tail.get("appendix", ""),
                disclaimer=tail.get("disclaimer", ""),
                terms=tail.get("terms", []),
                answer_kind=meta.get("answer_kind"),
            )

            # reflective 재구성은 final_state에 없는 turn_history를 빈 리스트로 되돌리므로,
            # 직전 이력을 명시적으로 이어붙인다(제외 목록에 두고 아래서 직접 세팅).
            updated_session = DPartSessionState(
                **{
                    name: final_state[name]
                    for name in DPartSessionState.model_fields
                    if name in final_state and name != "turn_history"
                }
            )
            updated_session.turn_history = [*session_state.turn_history, snapshot]
            await update_session_state(conversation_id, user.id, updated_session.model_dump(mode="json"))

            await save_message(user.id, "d", "assistant", final_answer, conversation_id)
            background_tasks.add_task(
                maybe_summarize_conversation, conversation_id, user.id, settings.summary_trigger_turns
            )

            yield f"data: {StreamEvent(type=EventType.DONE).model_dump_json()}\n\n"
        except Exception:
            logger.exception("d_part chat 처리 실패 (conversation_id=%s, user_id=%s)", conversation_id, user.id)
            # 사용자 발화만 남고 응답이 없는 반쪽 레코드를 막기 위해 assistant 에러 안내를 저장한다.
            # (이 저장마저 실패하면 로그만 남기고 error 이벤트는 그대로 내보낸다)
            try:
                await save_message(user.id, "d", "assistant", _ERROR_MESSAGE, conversation_id)
                # 복원(turn_history)에서도 이 턴이 빠지지 않도록 에러 스냅샷을 남긴다.
                # 대부분의 예외는 상태 저장 전에 나므로 session_state(직전 이력)에 이어붙인다.
                error_session = session_state.model_copy(update={
                    "turn_history": [
                        *session_state.turn_history,
                        DPartAnswerSnapshot(user_input=request.user_input, text=_ERROR_MESSAGE),
                    ]
                })
                await update_session_state(
                    conversation_id, user.id, error_session.model_dump(mode="json")
                )
            except Exception:
                logger.exception("에러 placeholder 저장 실패 (conversation_id=%s)", conversation_id)
            yield f"data: {StreamEvent(type=EventType.ERROR, data=_ERROR_MESSAGE).model_dump_json()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", background=background_tasks)


@router.get("/conversations/{conversation_id}")
async def get_d_conversation(conversation_id: int, user=Depends(get_current_user)):
    """사이드바에서 저장된 D 대화를 다시 열 때, 복원용 세션 상태(turn_history 포함)를 돌려준다.
    get_session_state가 소유권을 검증한다 — 타인/미존재 대화방이면 ConversationNotFoundError → 404."""
    raw_state = await get_session_state(conversation_id, user.id)
    session_state = DPartSessionState.model_validate(raw_state) if raw_state else DPartSessionState()
    return session_state.model_dump(mode="json")
