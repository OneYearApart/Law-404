"""사용자 후속 답변을 q01~q20 슬롯 상태에 반영한다."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from app.consultation.a_part.models import (
    ConversationState,
    FactSource,
    SlotStatus,
    utc_now,
)


PROJECT_ROOT = Path(__file__).resolve().parents[4]

DEFAULT_EXTRACTION_MODEL = "gpt-4o-mini"
SlotValue = str | bool | int | float | list[str] | None


class ExtractedSlotUpdate(BaseModel):
    """모델 또는 호출자가 제안한 슬롯 변경 한 건."""

    issue_id: str
    slot_key: str
    status: SlotStatus = SlotStatus.CONFIRMED
    value: SlotValue = None
    evidence_text: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    resolve_conflict: bool = False


class SlotExtractionResult(BaseModel):
    updates: list[ExtractedSlotUpdate] = Field(default_factory=list)
    unparsed_text: str | None = None


class AppliedSlotUpdate(BaseModel):
    issue_id: str
    slot_key: str
    previous_status: SlotStatus
    current_status: SlotStatus
    previous_value: SlotValue = None
    current_value: SlotValue = None
    conflict_created: bool = False
    conflict_resolved: bool = False


class SlotUpdateSummary(BaseModel):
    applied: list[AppliedSlotUpdate] = Field(default_factory=list)
    ignored: list[str] = Field(default_factory=list)

    @property
    def changed_count(self) -> int:
        return len(self.applied)


class SlotUpdateExtractor(Protocol):
    def extract(
        self,
        *,
        user_text: str,
        state: ConversationState,
    ) -> SlotExtractionResult:
        ...


def _normalize_compare(value: SlotValue) -> object:
    if isinstance(value, str):
        return " ".join(value.strip().lower().split())
    if isinstance(value, list):
        return tuple(
            " ".join(str(item).strip().lower().split())
            for item in value
        )
    return value


def _values_equal(left: SlotValue, right: SlotValue) -> bool:
    return _normalize_compare(left) == _normalize_compare(right)


def _unique_values(values: list[object]) -> list[object]:
    result: list[object] = []
    normalized: list[object] = []

    for value in values:
        comparable = _normalize_compare(value)  # type: ignore[arg-type]
        if comparable in normalized:
            continue
        normalized.append(comparable)
        result.append(value)

    return result


def _allowed_slot_payload(state: ConversationState) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []

    for issue_id in state.all_issue_ids:
        for slot in state.issue_slots.get(issue_id, {}).values():
            payload.append(
                {
                    "issue_id": issue_id,
                    "slot_key": slot.key,
                    "label": slot.label,
                    "question": slot.question,
                    "current_status": slot.status.value,
                    "current_value": slot.value,
                }
            )

    return payload


def extract_active_question_update(
    *,
    user_text: str,
    state: ConversationState,
) -> ExtractedSlotUpdate | None:
    """직전에 한 개씩 물은 질문에 대한 짧고 명확한 답을 우선 반영한다."""

    question_key = state.active_question_key
    if not question_key or ":" not in question_key:
        return None
    issue_id, slot_key = question_key.split(":", 1)
    slot = state.issue_slots.get(issue_id, {}).get(slot_key)
    if slot is None:
        return None

    normalized = " ".join(str(user_text or "").split()).strip()
    if not normalized:
        return None
    compact = re.sub(r"[^0-9a-z가-힣]", "", normalized.lower())

    asks_for_value = any(
        marker in slot.question
        for marker in ("누구", "언제", "얼마", "무엇", "어디", "어떤", "어떻게")
    )
    boolean_question = not asks_for_value and (
        slot.key.endswith((
            "_confirmed",
            "_checked",
            "_completed",
            "_received",
            "_kept",
            "_planned",
            "_available",
            "_effective",
            "_agreed",
            "_exists",
        ))
        or slot.question.endswith(("나요?", "있나요?", "했나요?"))
    )

    explicit_unknown_markers = (
        "잘모르",
        "모르겠",
        "기억안",
        "불확실",
        "해당없",
    )
    if any(marker in compact for marker in explicit_unknown_markers):
        return ExtractedSlotUpdate(
            issue_id=issue_id,
            slot_key=slot_key,
            status=SlotStatus.UNCERTAIN,
            value=None,
            evidence_text=normalized,
            confidence=1.0,
        )

    if boolean_question:
        negative_markers = (
            "아니",
            "없",
            "못받",
            "안받",
            "못했",
            "안했",
            "확인못",
            "확인하지못",
            "아직안",
            "아직못",
        )
        if any(marker in compact for marker in negative_markers):
            return ExtractedSlotUpdate(
                issue_id=issue_id,
                slot_key=slot_key,
                status=SlotStatus.CONFIRMED,
                value=False,
                evidence_text=normalized,
                confidence=1.0,
            )

        positive_markers = (
            "네",
            "예",
            "맞",
            "확인했",
            "받았",
            "했어요",
            "있어요",
            "완료",
            "직접통화",
        )
        if any(marker in compact for marker in positive_markers):
            return ExtractedSlotUpdate(
                issue_id=issue_id,
                slot_key=slot_key,
                status=SlotStatus.CONFIRMED,
                value=True,
                evidence_text=normalized,
                confidence=1.0,
            )

    # 이름·금액처럼 값 자체를 묻는 질문에서 "아직 확인하지 못했습니다"라고
    # 답한 경우에도 해당 질문에는 응답한 것으로 기록한다.
    value_unknown_markers = (
        "아직확인하지못",
        "아직확인못",
        "확인하지못",
        "미확인",
    )
    if not boolean_question and any(
        marker in compact for marker in value_unknown_markers
    ):
        return ExtractedSlotUpdate(
            issue_id=issue_id,
            slot_key=slot_key,
            status=SlotStatus.UNCERTAIN,
            value=None,
            evidence_text=normalized,
            confidence=1.0,
        )

    # 값 자체를 묻는 질문에는 "네, 확인했어요" 같은 대답을 값으로 저장하지 않는다.
    vague_affirmatives = {
        "네", "예", "네확인했어요", "예확인했어요", "확인했어요", "맞아요"
    }
    if not boolean_question and compact in vague_affirmatives:
        return None

    # 짧은 단답은 현재 질문의 값으로 사용할 수 있다. 긴 문장은 LLM 추출기로 넘긴다.
    if len(normalized) <= 40 and not boolean_question:
        return ExtractedSlotUpdate(
            issue_id=issue_id,
            slot_key=slot_key,
            status=SlotStatus.CONFIRMED,
            value=normalized,
            evidence_text=normalized,
            confidence=1.0,
        )
    return None


class OpenAISlotUpdateExtractor:
    """현재 활성 슬롯만 보여 주고 사용자 발화에서 명시된 사실을 추출한다."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        try:
            from dotenv import load_dotenv
        except ImportError:
            load_dotenv = None

        if load_dotenv is not None:
            load_dotenv(PROJECT_ROOT / "backend" / ".env")
            load_dotenv(PROJECT_ROOT / ".env")

        try:
            from openai import OpenAI
        except ImportError as error:
            raise RuntimeError(
                "openai 패키지가 없어 후속 답변 슬롯 분석기를 만들 수 없습니다."
            ) from error

        resolved_key = api_key or os.getenv("OPENAI_API_KEY")
        resolved_model = (
            model
            or os.getenv("OPENAI_CHAT_MODEL")
            or DEFAULT_EXTRACTION_MODEL
        ).strip()

        if not resolved_key:
            raise RuntimeError(
                "OPENAI_API_KEY가 없어 후속 답변의 슬롯을 분석할 수 없습니다. "
                "backend/.env를 확인하세요."
            )

        self._client = OpenAI(api_key=resolved_key)
        self._model = resolved_model or DEFAULT_EXTRACTION_MODEL

    def extract(
        self,
        *,
        user_text: str,
        state: ConversationState,
    ) -> SlotExtractionResult:
        normalized = user_text.strip()
        if not normalized:
            raise ValueError("user_text는 빈 문자열일 수 없습니다.")

        recent_questions = []
        if state.last_answer:
            answer = state.last_answer.get("answer", state.last_answer)
            if isinstance(answer, dict):
                recent_questions = list(
                    answer.get("follow_up_questions") or []
                )[:3]

        system_prompt = """
너는 Law 404 상담 상태 추출기다.
사용자의 현재 발화에서 명시적으로 확인되는 사실만 허용된 슬롯에 반영한다.

규칙:
1. 허용된 issue_id와 slot_key만 사용한다.
2. 사용자가 말하지 않은 사실은 절대 추측하지 않는다.
3. 예/완료/확인함처럼 분명한 답은 status=confirmed, value=true로 작성한다.
4. 아니요/없음/미완료처럼 분명한 부정 답도 status=confirmed, value=false로 작성한다.
5. 이름·금액·날짜·문구는 사용자가 말한 값을 가능한 그대로 value에 넣는다.
6. 모르겠음·아직 못 봄·확인하지 못함은 status=uncertain으로 작성한다.
7. 현재 상황에 적용되지 않는다고 명시한 경우만 status=not_applicable로 작성한다.
8. 앞선 답을 바꾸는 내용이어도 새 값을 추출하되, 자동으로 기존 값을 지우지 않는다.
9. 이미 conflict 상태인 값을 사용자가 자료를 다시 확인한 뒤 최종 확정한다고 명시한 경우만 resolve_conflict=true로 작성한다.
10. 한 문장에서 여러 슬롯이 확인되면 모두 반환한다.
11. 슬롯과 연결할 수 없는 문장은 updates에 넣지 않고 unparsed_text에 남긴다.
""".strip()

        user_prompt = "\n".join(
            [
                "[활성 슬롯]",
                json.dumps(
                    _allowed_slot_payload(state),
                    ensure_ascii=False,
                    default=str,
                ),
                "",
                "[직전 추가 질문]",
                json.dumps(recent_questions, ensure_ascii=False),
                "",
                "[사용자 발화]",
                normalized,
            ]
        )

        try:
            response = self._client.responses.parse(
                model=self._model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                text_format=SlotExtractionResult,
            )
        except Exception as error:
            raise RuntimeError(
                f"후속 답변 슬롯 추출 실패: {error}"
            ) from error

        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError("후속 답변 슬롯 추출 결과가 비어 있습니다.")
        return parsed


def apply_slot_updates(
    state: ConversationState,
    updates: list[ExtractedSlotUpdate],
    *,
    strict: bool = False,
) -> SlotUpdateSummary:
    """추출 결과를 상태에 반영하고 서로 다른 확정값은 conflict로 남긴다."""

    summary = SlotUpdateSummary()

    for update in updates:
        issue_slots = state.issue_slots.get(update.issue_id)
        if issue_slots is None:
            message = f"활성 상담에 없는 issue_id: {update.issue_id}"
            if strict:
                raise ValueError(message)
            summary.ignored.append(message)
            continue

        slot = issue_slots.get(update.slot_key)
        if slot is None:
            message = (
                f"{update.issue_id}에 없는 slot_key: {update.slot_key}"
            )
            if strict:
                raise ValueError(message)
            summary.ignored.append(message)
            continue

        if update.status == SlotStatus.CONFLICT:
            message = (
                "extractor는 conflict를 직접 지정할 수 없습니다. "
                "서로 다른 confirmed 값이 들어오면 서버가 생성합니다."
            )
            if strict:
                raise ValueError(message)
            summary.ignored.append(message)
            continue

        if (
            update.status == SlotStatus.CONFIRMED
            and update.value is None
        ):
            message = (
                f"confirmed 값이 비어 있음: {update.issue_id}.{update.slot_key}"
            )
            if strict:
                raise ValueError(message)
            summary.ignored.append(message)
            continue

        previous_status = slot.status
        previous_value = slot.value
        conflict_created = False
        conflict_resolved = False

        if update.status == SlotStatus.CONFIRMED:
            if (
                previous_status == SlotStatus.CONFIRMED
                and not _values_equal(previous_value, update.value)
            ):
                slot.status = SlotStatus.CONFLICT
                slot.conflicting_values = _unique_values(
                    [previous_value, update.value]
                )
                slot.value = None
                conflict_created = True
            elif previous_status == SlotStatus.CONFLICT:
                if update.resolve_conflict:
                    slot.status = SlotStatus.CONFIRMED
                    slot.value = update.value
                    slot.conflicting_values = []
                    conflict_resolved = True
                else:
                    slot.conflicting_values = _unique_values(
                        [*slot.conflicting_values, update.value]
                    )
            else:
                slot.status = SlotStatus.CONFIRMED
                slot.value = update.value
                slot.conflicting_values = []
        elif update.status == SlotStatus.NOT_APPLICABLE:
            # 대리 계약의 핵심 7개 질문은 모두 실제 판단에 필요한 항목이다.
            # extractor가 "해당 없음"으로 잘못 분류해도 완료 사실로 처리하지 않는다.
            if update.issue_id == "q01_owner_proxy":
                slot.status = SlotStatus.UNCERTAIN
                slot.value = None
            else:
                slot.status = SlotStatus.NOT_APPLICABLE
                slot.value = update.value
            slot.conflicting_values = []
        else:
            # 기존 확정값 뒤에 모호한 답이 들어오면 확정 사실을 조용히 지우지 않고
            # 재확인이 필요한 conflict 상태로 올린다.
            if previous_status == SlotStatus.CONFIRMED:
                slot.status = SlotStatus.CONFLICT
                slot.value = None
                slot.conflicting_values = _unique_values(
                    [previous_value, update.value or "uncertain"]
                )
                conflict_created = True
            else:
                slot.status = SlotStatus.UNCERTAIN
                slot.value = update.value

        slot.source = FactSource.USER
        slot.evidence_text = (
            update.evidence_text.strip()
            if update.evidence_text
            else None
        )
        slot.updated_at = utc_now()

        summary.applied.append(
            AppliedSlotUpdate(
                issue_id=update.issue_id,
                slot_key=update.slot_key,
                previous_status=previous_status,
                current_status=slot.status,
                previous_value=previous_value,
                current_value=slot.value,
                conflict_created=conflict_created,
                conflict_resolved=conflict_resolved,
            )
        )

    if summary.applied:
        state.touch()

    return summary
