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


# supervisor(nodes/supervisor.py)의 분류 대상 카테고리와 실행 노드(general_scenario.py/
# special_cases.py)가 참조하는 라벨이 서로 어긋나지 않도록 여기 한 곳에서만 정의한다.
GENERAL_TOPIC_LABELS: dict[str, str] = {
    "전-①등기부등본_위험신호": "등기부등본 위험 신호 해석(근저당, 가압류, 소유권 이전 이력)",
    "전-②전세가율_HUG보증보험": "전세가율/HUG 보증보험 가입 가능 여부 미확인",
    "전-③다가구_선순위보증금": "다가구주택 선순위 보증금 미확인",
    "전-④계약서_특약사항": "계약서 특약사항 위험 조항 해석",
    "전-⑤신탁사기": "임대인 실제 소유자 여부(신탁사기)",
    "전-⑥공인중개사_허위고지": "공인중개사 허위/누락 고지",
    "중-①소유권_변동모니터링": "소유권 변동 모니터링",
    "중-②근저당_추가설정": "근저당 추가 설정 모니터링",
    "중-③임대인_세금체납": "임대인 세금 체납 확인",
    "중-④갱신시점_위험": "갱신 시점 위험(갱신료 요구, 갱신 거절 빙자 사기)",
    "중-⑤다가구_타세입자_피해": "다가구주택 타 세입자 피해 소식(조기경보)",
    "후-①대항력_우선변제권_상실": "대항력/우선변제권 상실 위험",
    "후-②이중계약_배당순위": "이중계약/배당 순위 다툼",
}

SPECIAL_CASE_CATEGORIES: tuple[str, ...] = ("임대인 사망/파산", "신탁사기", "다가구주택", "공인중개사 허위고지")

# supervisor가 분류하는 특수상황 4종 → search_by_topic이 조회할 topic_tag 키 매핑(작업단위 49).
# 키는 links_d.py TOPIC_TAG_KEYWORDS와 정확히 일치해야 한다(§4대로 4종 전부 판례/HUG 태그 보유).
SPECIAL_CASE_TOPIC_TAGS: dict[str, str] = {
    "임대인 사망/파산": "트리거-임대인사망파산",
    "신탁사기": "전-⑤신탁사기",
    "다가구주택": "전-③다가구_선순위보증금",
    "공인중개사 허위고지": "전-⑥공인중개사_허위고지",
}


class VictimRequirementSlots(BaseModel):
    moved_in_and_fixed_date: Optional[SlotStatus] = None      # ① 전입신고+확정일자
    deposit_under_limit: Optional[SlotStatus] = None            # ② 보증금 한도
    multiple_victims: Optional[SlotStatus] = None                # ③ 2인 이상 피해
    no_intent_to_return: Optional[SlotStatus] = None             # ④ 반환의도 없음 의심
    multiple_victims_reason: Optional[str] = None                  # ③의 구체적 근거(파산회생/경공매개시/압류/집행권원 등) 텍스트 기록
    # 아래 두 필드는 ①~④ 요건과 별개의 통제 플래그 (참고: D파트_구현_종합문서.md §9.1)
    auction_completed: Optional[bool] = None                       # 경공매완료여부 — true면 ①③ 자유서술만으로 자동충족 처리
    has_relief_measure: Optional[bool] = None                      # 구제수단보유여부 — true면 판단 결과를 "제외"로 덮어씀. 자유서술 추론 금지, 명시 확인질문 필수


# 요건 슬롯의 사람이 읽는 이름. LLM 컨텍스트에 필드명(moved_in_and_fixed_date 등)을 그대로
# 넘기면 모델이 그 영문 키를 답변에 그대로 옮겨 적는다 — 사용자에게 내부 변수명이 노출된다.
VICTIM_SLOT_LABELS = {
    "moved_in_and_fixed_date": "전입신고·확정일자(대항력·우선변제권)",
    "deposit_under_limit": "보증금 한도 이내",
    "multiple_victims": "다수 피해 발생(예상)",
    "no_intent_to_return": "임대인의 반환의도 부재를 의심할 상당한 이유",
}


class DPartGraphState(TypedDict, total=False):
    """LangGraph 1회 실행 동안만 유효한 전체 상태. 턴 종료 시 폐기되며,
    다음 턴으로 넘겨야 하는 부분집합만 DPartSessionState로 골라 영속화합니다.
    """
    user_input: str                                # 이번 턴 사용자 발화 원문 — 매 턴 새로 옴, carryover 아님
    active_query: Optional[str]                       # 확인 게이트 대기 중 스택된 "실질적 질문" 원문.
                                                         # 게이트를 소유한 노드(현재는 stage_router)가 생애주기를
                                                         # 관리하며, 그 외 노드는 get_active_query()로만 읽는다
    session_id: Optional[str]                        # = conversations.id. 상태를 어디서 불러올지 가리키는 키일 뿐, 값 자체는 아님
    persona: Optional[str]                             # 사용자 유형(임차인/임대인 등) — 최초 판별 후 유지
    stage: Optional[Stage]                              # 계약 단계(전/중/후) — supervisor가 general_topic 키
                                                           # 접두어에서 역산(단위 29). 역산 불가한 턴은 이전 값 유지
    route_target: Optional[str]                             # supervisor가 이번 턴 결정한 다음 노드
                                                               # ("victim_check"/"special_cases"/"general_scenario"/
                                                               # "open_qa") — 이번 턴 라우팅 전용, carryover 아님
    victim_slots: VictimRequirementSlots                     # 요건 슬롯 누적 결과 — 이 기능의 핵심 carryover 데이터
    victim_judgment: Optional[VictimJudgment]                 # 판단 결과(높음/있음/추가확인)
    victim_fallback: bool                                       # 반복 질문에도 슬롯 미충족 시 전문가 상담 안내로 폴백했는지
    victim_flow_closed: bool                                      # 인터뷰가 종결됐는지(판정 확정/지원대상 제외/fallback).
                                                                     # True면 supervisor가 이번 턴 발화를 정상 재분류한다
    victim_check_attempts: int                                   # 슬롯 진전 없이 머문 연속 턴 수 — fallback 판단용
    victim_pending_slot: Optional[str]                             # 직전 턴에 질문을 던진 슬롯 이름 — 이번 턴 발화가
                                                                     # "아니요" 같은 맥락 의존 답변일 때 어느 슬롯에 대한
                                                                     # 답인지 추출기에 알려주는 용도. carryover 필수
    awaiting_relief_confirmation: bool                             # 구제수단보유여부 명시적 질문에 대한 응답을 기다리는 중인지
    needs_response_assembly: bool                                     # victim_check가 이번 턴에 판단을 새로 확정했는지 —
                                                                        # response_assembly 실행 조건, 이번 턴 전용(carryover 아님)
    answer_kind: Optional[str]                                        # 이번 턴 답변의 성격(judgment/scenario/
                                                                        # special_case/open_qa). 응답을 만든 노드가
                                                                        # 세팅한다 — 라우트가 route_target에서 재역산하면
                                                                        # 실제 경로와 어긋날 수 있다. 이번 턴 전용
    disclaimer_text: Optional[str]                                    # 이번 턴 응답에 붙일 면책 문구 — 스트림 경로에서
                                                                        # finalize가 세팅하고 호출부가 본문 뒤에 붙인다.
                                                                        # 고정 텍스트 경로는 final_answer에 직접 인라인. 이번 턴 전용
    appendix_text: Optional[str]                                      # 스트림 말미(면책 앞)에 붙일 결정론적 첨부 텍스트 —
                                                                        # 미인지형 지원절차 액션플랜(43~45) / 인지형 지원절차 개요(49)가 공유.
                                                                        # finalize가 첨부. 이번 턴 전용(carryover 아님)
    special_case_matched: Optional[str]                          # 매칭된 특수상황
    general_topic_matched: Optional[str]                           # 매칭된 일반 시나리오 항목(13개 항목 키) — 매 턴 재분류, carryover 아님
    retrieved_chunks: list[dict[str, Any]]                         # RAG 검색 결과 — 이번 턴 전용, carryover 아님
    # TODO: app/rag 쪽에 전용 Chunk 타입이 생기면 list[Chunk]로 교체 (2026-07-11 기준 미존재)
    final_answer: Optional[str]                                     # 이번 턴 최종 답변 — messages 테이블에 별도 저장되므로 state에 중복 보관 안 함
    disclaimer_required: bool                                        # 이번 턴 final_answer가 법률 정보 응답이라 면책 문구가 필요한지
                                                                       # (확인질문/fallback엔 False). LLM 스트림 경로는 finalize가 항상 첨부. 이번 턴 전용
    response_stream: Optional[AsyncIterator[str]]                    # 스트리밍 청크 제너레이터 — JSON 직렬화 불가, 절대 영속화 금지


class DPartSessionState(BaseModel):
    """conversations.state(JSONB)에 그대로 직렬화되는 턴 간 carryover 상태.
    다음 턴 시작 시 이 값으로 DPartGraphState의 대응 필드를 미리 채워 넣습니다.
    저장: state.model_dump(mode="json") / 로드: DPartSessionState.model_validate(raw_dict)
    """
    stage: Optional[Stage] = None
    active_query: Optional[str] = None
    persona: Optional[str] = None
    victim_slots: VictimRequirementSlots = Field(default_factory=VictimRequirementSlots)
    victim_judgment: Optional[VictimJudgment] = None
    victim_fallback: bool = False
    victim_flow_closed: bool = False
    victim_check_attempts: int = 0
    victim_pending_slot: Optional[str] = None
    awaiting_relief_confirmation: bool = False
    special_case_matched: Optional[str] = None


def get_active_query(state: DPartGraphState) -> str:
    """이번 턴 분류/매칭에 쓸 '실질적 사용자 발화'를 반환한다.
    active_query가 채워져 있으면 그 값(확인 게이트 대기 중 이전 턴에 스택해둔 원문)을,
    없으면 이번 턴 원문(user_input)을 그대로 반환한다.

    컨벤션 (새로운 확인 게이트를 추가할 때 지켜야 할 규칙):
      1) 게이트 질문을 처음 세팅하는 턴 — active_query를 이번 턴 user_input으로 세팅
      2) 게이트 응답(긍정)을 받아 게이트를 통과시키는 턴 — active_query를 건드리지 않음
         (다음 노드들이 이번 턴 raw user_input 대신 이 값을 읽어야 하므로)
      3) 게이트 응답(부정)을 받아 리셋하는 턴 — active_query를 None으로 비움
      4) 게이트 응답을 못 알아들어 재질문하는 턴 — active_query를 건드리지 않음

    분류/매칭 로직만 있는 노드(supervisor, open_qa)는 이 함수를 통해서만 "분류 대상
    텍스트"에 접근해야 하며, 게이트 자체를 소유한 노드(stage_router)나 자기 완결적
    게이트를 가진 노드(victim_check의 awaiting_relief_confirmation)는 그대로 raw
    user_input을 써도 된다 — 그 응답이 "예/아니오"류 제어신호일 뿐 재추출할 실질
    콘텐츠가 없기 때문이다.
    """
    return state.get("active_query") or state["user_input"]
