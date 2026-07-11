"""
D파트 그래프 상태 및 요건 슬롯 정의.

- SlotStatus / VictimRequirementSlots: 전세사기피해자법 제3조 요건 슬롯
- Stage / VictimJudgment: 계약 단계, 판단 결과 어휘
- DPartGraphState: LangGraph 1회 실행(.ainvoke() 1건 = HTTP 요청 1건) 동안만 유효한 전체 상태
- DPartSessionState: 턴을 넘어 conversations.state(JSONB)에 영속화되는 부분집합
  (둘을 분리한 이유는 DPartSessionState 문서 참고)

요건 슬롯 목록은 전세사기피해자법 조문 확인 후 확정 예정.
현재까지 확인된 제3조 피해자 요건 4가지:
  ① 전입신고 + 확정일자
  ② 보증금 5억 이하 (최대 7억 상향 가능)
  ③ 2인 이상 피해(예상)
  ④ 반환의도 없음을 의심할 상당한 이유
"""
from enum import Enum
from typing import Any, AsyncIterator, Optional, TypedDict

from pydantic import BaseModel, Field


class SlotStatus(str, Enum):
    FILLED = "filled"
    UNFILLED = "unfilled"
    UNCLEAR = "unclear"


class Stage(str, Enum):
    PRE = "전"
    DURING = "중"
    POST = "후"


class VictimJudgment(str, Enum):
    HIGH = "높음"
    PRESENT = "있음"
    NEEDS_CONFIRMATION = "추가확인"


class VictimRequirementSlots(BaseModel):
    moved_in_and_fixed_date: Optional[SlotStatus] = None      # ① 전입신고+확정일자
    deposit_under_limit: Optional[SlotStatus] = None            # ② 보증금 한도
    multiple_victims: Optional[SlotStatus] = None                # ③ 2인 이상 피해
    no_intent_to_return: Optional[SlotStatus] = None             # ④ 반환의도 없음 의심
    multiple_victims_reason: Optional[str] = None                  # ③의 구체적 근거(파산회생/경공매개시/압류/집행권원 등) 텍스트 기록
    # 아래 두 필드는 ①~④ 요건과 별개의 통제 플래그 (참고: D파트_구현_종합문서.md §9.1)
    auction_completed: Optional[bool] = None                       # 경공매완료여부 — true면 ①③ 자유서술만으로 자동충족 처리
    has_relief_measure: Optional[bool] = None                      # 구제수단보유여부 — true면 판단 결과를 "제외"로 덮어씀. 자유서술 추론 금지, 명시 확인질문 필수


class DPartGraphState(TypedDict, total=False):
    """LangGraph 1회 실행 동안만 유효한 전체 상태. 턴 종료 시 폐기되며,
    다음 턴으로 넘겨야 하는 부분집합만 DPartSessionState로 골라 영속화합니다.
    """
    user_input: str                                # 이번 턴 사용자 발화 원문 — 매 턴 새로 옴, carryover 아님
    session_id: Optional[str]                        # = conversations.id. 상태를 어디서 불러올지 가리키는 키일 뿐, 값 자체는 아님
    persona: Optional[str]                             # 사용자 유형(임차인/임대인 등) — 최초 판별 후 유지
    stage: Optional[Stage]                              # 계약 단계(전/중/후) — 최초 판별+확인 후 유지
    stage_confirmed: bool                                 # stage가 사용자 확인을 거쳤는지
    risk_trigger_detected: bool                            # 이번 턴 위험신호 감지 여부 — 매 턴 재계산, carryover 아님
    risk_trigger_reason: Optional[str]                      # 위 감지 근거 — 역시 매 턴 재계산
    victim_slots: VictimRequirementSlots                     # 요건 슬롯 누적 결과 — 이 기능의 핵심 carryover 데이터
    victim_judgment: Optional[VictimJudgment]                 # 판단 결과(높음/있음/추가확인)
    victim_fallback: bool                                       # 반복 질문에도 슬롯 미충족 시 전문가 상담 안내로 폴백했는지
    victim_check_attempts: int                                   # 슬롯 진전 없이 머문 연속 턴 수 — fallback 판단용
    awaiting_relief_confirmation: bool                             # 구제수단보유여부 명시적 질문에 대한 응답을 기다리는 중인지
    special_case_matched: Optional[str]                          # 매칭된 특수상황
    retrieved_chunks: list[dict[str, Any]]                         # RAG 검색 결과 — 이번 턴 전용, carryover 아님
    # TODO: app/rag 쪽에 전용 Chunk 타입이 생기면 list[Chunk]로 교체 (2026-07-11 기준 미존재)
    final_answer: Optional[str]                                     # 이번 턴 최종 답변 — messages 테이블에 별도 저장되므로 state에 중복 보관 안 함
    response_stream: Optional[AsyncIterator[str]]                    # 스트리밍 청크 제너레이터 — JSON 직렬화 불가, 절대 영속화 금지


class DPartSessionState(BaseModel):
    """conversations.state(JSONB)에 그대로 직렬화되는 턴 간 carryover 상태.
    다음 턴 시작 시 이 값으로 DPartGraphState의 대응 필드를 미리 채워 넣습니다.
    저장: state.model_dump(mode="json") / 로드: DPartSessionState.model_validate(raw_dict)
    """
    stage: Optional[Stage] = None
    stage_confirmed: bool = False
    persona: Optional[str] = None
    victim_slots: VictimRequirementSlots = Field(default_factory=VictimRequirementSlots)
    victim_judgment: Optional[VictimJudgment] = None
    victim_fallback: bool = False
    victim_check_attempts: int = 0
    awaiting_relief_confirmation: bool = False
    special_case_matched: Optional[str] = None
