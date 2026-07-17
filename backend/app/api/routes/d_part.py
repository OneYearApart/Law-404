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
from app.graph.parts.d_part.schemas import DPartSessionState
from app.rag.retrievers.d_part import DPartRetriever

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat/d", tags=["d_part"])

# 용어사전 조회 전용 — 사전은 프로세스당 1회만 읽고 캐시된다(load_glossary 참고).
_retriever = DPartRetriever()

_ERROR_MESSAGE = "일시적인 오류로 응답을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."


class DPartChatRequest(BaseModel):
    conversation_id: int
    user_input: str


def _answer_kind(final_state: dict) -> str | None:
    """이번 턴 답변의 성격. supervisor가 이미 분류해둔 결과(route_target)에서 역산한다.

    route_target='victim_check'는 답변이 두 종류다 — 요건을 더 묻는 턴과 판정이 확정된 턴.
    스트림을 만드는 건 후자뿐이므로 needs_response_assembly로 가른다(배지와 같은 게이트).
    확인질문/fallback처럼 성격을 규정할 게 없는 턴은 None을 반환해 아예 싣지 않는다.
    """
    if final_state.get("needs_response_assembly"):
        return "judgment"
    if final_state.get("special_case_matched"):
        return "special_case"
    if final_state.get("general_topic_matched"):
        return "scenario"
    if final_state.get("route_target") == "open_qa":
        return "open_qa"
    return None


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
            graph_input = {
                name: getattr(session_state, name) for name in DPartSessionState.model_fields
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
            # "이번 턴에 새로 확정했는지" 플래그(action_plan/response_assembly와 동일 게이트).
            # 지원대상 제외 경로는 victim_judgment가 None이라 자연히 빠진다.
            if final_state.get("needs_response_assembly") and final_state.get("victim_judgment"):
                meta["judgment"] = final_state["victim_judgment"].value

            # 답변 성격을 함께 알린다. 네 경로가 같은 프롬프트(response.md)를 태우지만 내용은
            # 다르다 — 판정 없는 턴의 '상황적용'은 내 상황 판단이 아니라 일반 유의사항이다
            # (response.md가 "판단 결과가 주어지지 않았다면 위험도를 붙이지 말라"고 지시).
            # 클라이언트가 이걸 모르면 모든 답에 같은 제목을 달아 내용과 어긋난다.
            answer_kind = _answer_kind(final_state)
            if answer_kind:
                meta["answer_kind"] = answer_kind

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
            body_text = "".join(chunks)
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

            updated_session = DPartSessionState(
                **{name: final_state[name] for name in DPartSessionState.model_fields if name in final_state}
            )
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
            except Exception:
                logger.exception("에러 placeholder 저장 실패 (conversation_id=%s)", conversation_id)
            yield f"data: {StreamEvent(type=EventType.ERROR, data=_ERROR_MESSAGE).model_dump_json()}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", background=background_tasks)
