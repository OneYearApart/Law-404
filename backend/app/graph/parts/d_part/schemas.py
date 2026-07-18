"""
D파트 그래프 상태 및 요건 슬롯 정의.

- SlotStatus / VictimRequirementSlots: 전세사기피해자법 제3조 요건 슬롯
- VictimJudgment: 판단 결과 어휘
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

from pydantic import BaseModel, Field, field_validator


class SlotStatus(str, Enum):
    FILLED = "filled"
    UNFILLED = "unfilled"
    UNCLEAR = "unclear"


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

# supervisor가 판별하는 위험신호 6종. prompts/supervisor.md에 산문으로만 있던 목록을
# 키로 고정한 것 — SituationState.risk_signals의 어휘이자 supervisor tool의 enum이라,
# 여기서 한 번만 정의해야 프롬프트·스키마·라우팅이 같은 값을 두고 판단한다.
RISK_SIGNALS: tuple[str, ...] = (
    "경공매개시",        # 경매/공매 개시 통지를 받음
    "보증금미반환",      # 보증금을 돌려받지 못하고 있음
    "임대인연락두절",    # 임대인과 연락이 안 됨
    "임대인사망파산",    # 임대인 사망/파산 소식
    "소유권변동",        # 경매낙찰·명의이전 등 소유권 변동을 알게 됨
    "다수피해",          # 같은 집주인에게 다른 세입자도 피해
)

# supervisor가 분류하는 특수상황 4종 → search_by_topic이 조회할 topic_tag 키 매핑(작업단위 49).
# 키는 links_d.py TOPIC_TAG_KEYWORDS와 정확히 일치해야 한다(§4대로 4종 전부 판례/HUG 태그 보유).
SPECIAL_CASE_TOPIC_TAGS: dict[str, str] = {
    "임대인 사망/파산": "트리거-임대인사망파산",
    "신탁사기": "전-⑤신탁사기",
    "다가구주택": "전-③다가구_선순위보증금",
    "공인중개사 허위고지": "전-⑥공인중개사_허위고지",
}

# 일반주제 ↔ 특수상황 4종은 일부가 "같은 상황의 인정 전/후"다 — 13개 항목 설명이 전-⑤/전-⑥을
# "아직 피해 인정 전 우려 단계"로 명시한다. 즉 어느 쪽이냐는 recognized 축이 정하지, 발화 내용이
# 정하는 게 아니다. 그 대응을 SPECIAL_CASE_TOPIC_TAGS에서 뒤집어 쓴다(별도 목록을 만들면 둘이
# 어긋난다). 트리거-임대인사망파산은 topic 키가 아니라 검색 태그라 여기서 빠진다.
SITUATION_TOPIC_TO_SPECIAL_CASE: dict[str, str] = {
    topic: case for case, topic in SPECIAL_CASE_TOPIC_TAGS.items() if topic in GENERAL_TOPIC_LABELS
}

# 같은 겹침을 반대로도 읽어야 한다 — 미인지형 발화에서 모델이 topic 대신 special_case만 채우는
# 경우가 있는데(골든셋 gen-005 실측), route()는 special_case를 recognized 블록 안에서만 읽으므로
# 그대로 두면 상황을 정확히 판별하고도 open_qa로 떨어진다. 위 딕셔너리를 뒤집어 쓴다(같은 사실을
# 두 곳에 적으면 어긋난다). 임대인 사망/파산은 위에서 이미 걸러져 여기에도 없다.
SPECIAL_CASE_TO_SITUATION_TOPIC: dict[str, str] = {
    case: topic for topic, case in SITUATION_TOPIC_TO_SPECIAL_CASE.items()
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


class SituationState(BaseModel):
    """supervisor가 매 턴 갱신하는 '사용자가 지금 어떤 상황인가'의 단일 진실원천.

    도메인의 축(인지여부·위험신호·topic·특수상황)을 1급 필드로 둔다. 예전에는 이 축들이
    카테고리 enum 하나로 압축돼 있어, 축이 상충하는 발화에서 정보가 손실되고 부가기능이
    "어느 노드가 실행됐나"에 묶였다.
    특히 recognized와 topic이 별개 필드라, 한 축이 다른 축을 덮어쓸 자리가 구조적으로 없다.

    축은 실제로 라우팅이나 부가기능을 gate하는 것만 넣는다 — 소비처 없는 축은 넣지 않는다.
    계약 단계(전/중/후)를 여기 뒀다가 뺀 이유가 그거다: 아무도 읽지 않아 매 턴 LLM 판별 비용만
    쓰는 write-only 상태였고, 같은 정보가 필요한 곳엔 topic 키 접두어에 이미 들어 있었다.

    interview_active(victim_check 인터뷰 진행 중인지)와 라우팅 대상도 여기 두지 않는다.
    각각 기존 플래그와 이 상황모델에서 파생되는 값이라, 저장하면 진실원천이 둘이 된다.
    파생 로직은 supervisor.interview_in_progress / supervisor.route가 갖고 있다.
    """
    recognized: Optional[bool] = None       # 피해자로 인정받은 상태인지 — topic과 독립적으로 판별
    risk_signals: list[str] = Field(default_factory=list)   # RISK_SIGNALS 부분집합
    topic: Optional[str] = None               # GENERAL_TOPIC_LABELS 키 | None
    special_case: Optional[str] = None         # SPECIAL_CASE_CATEGORIES 중 하나 | None

    # OpenAI tool calling은 strict 모드가 아니면 enum을 강제하지 않는다 — 모델이 정의된 어휘 밖의
    # 값을 넘기는 걸 실호출로 확인했다(topic 키가 special_case 자리에 들어온 사례). 스키마에 enum을
    # 적어둔 것만으론 안전하지 않아서, 어휘 검증을 이 타입의 책임으로 둔다. 라우팅이 이 값을 그대로
    # 믿고 분기하므로 모르는 값은 받느니 버린다(None = 해당 없음, 이미 정상값이다).
    @field_validator("topic")
    @classmethod
    def _known_topic(cls, value: Optional[str]) -> Optional[str]:
        return value if value in GENERAL_TOPIC_LABELS else None

    @field_validator("special_case")
    @classmethod
    def _known_special_case(cls, value: Optional[str]) -> Optional[str]:
        return value if value in SPECIAL_CASE_CATEGORIES else None

    @field_validator("risk_signals")
    @classmethod
    def _known_risk_signals(cls, value: list[str]) -> list[str]:
        return [signal for signal in value if signal in RISK_SIGNALS]


class DPartGraphState(TypedDict, total=False):
    """LangGraph 1회 실행 동안만 유효한 전체 상태. 턴 종료 시 폐기되며,
    다음 턴으로 넘겨야 하는 부분집합만 DPartSessionState로 골라 영속화합니다.
    """
    user_input: str                                # 이번 턴 사용자 발화 원문 — 매 턴 새로 옴, carryover 아님
    situation: Optional[SituationState]               # supervisor가 매 턴 갱신하는 상황모델 — 축별 1급 상태.
                                                         # 라우팅·실행노드·부가기능이 참조할 단일 진실원천. carryover 대상.
                                                         # 라우팅 대상은 여기서 파생만 하고(supervisor.route) 저장하지
                                                         # 않는다 — 저장하면 진실원천이 둘이 된다
    session_id: Optional[str]                        # = conversations.id. 상태를 어디서 불러올지 가리키는 키일 뿐, 값 자체는 아님
    persona: Optional[str]                             # 사용자 유형(임차인/임대인 등) — 최초 판별 후 유지
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
                                                                        # special_case/recognized_general/open_qa).
                                                                        # 응답을 만든 노드가 세팅한다 — 호출부가 상황모델에서
                                                                        # 재역산하면 실제 경로와 어긋난다. 이번 턴 전용
    disclaimer_text: Optional[str]                                    # 이번 턴 응답에 붙일 면책 문구 — 스트림 경로에서
                                                                        # finalize가 세팅하고 호출부가 본문 뒤에 붙인다.
                                                                        # 고정 텍스트 경로는 final_answer에 직접 인라인. 이번 턴 전용
    appendix_text: Optional[str]                                      # 스트림 말미(면책 앞)에 붙일 결정론적 첨부 텍스트 —
                                                                        # 미인지형 지원절차 액션플랜(43~45) / 인지형 지원절차
                                                                        # 개요(special_cases 49, recognized_general)가 공유.
                                                                        # finalize가 첨부. 이번 턴 전용(carryover 아님)
    retrieved_chunks: list[dict[str, Any]]                         # RAG 검색 결과 — 이번 턴 전용, carryover 아님
    # TODO: app/rag 쪽에 전용 Chunk 타입이 생기면 list[Chunk]로 교체 (2026-07-11 기준 미존재)
    final_answer: Optional[str]                                     # 이번 턴 최종 답변 — messages 테이블에 별도 저장되므로 state에 중복 보관 안 함
    disclaimer_required: bool                                        # 이번 턴 final_answer가 법률 정보 응답이라 면책 문구가 필요한지
                                                                       # (확인질문/fallback엔 False). LLM 스트림 경로는 finalize가 항상 첨부. 이번 턴 전용
    response_stream: Optional[AsyncIterator[str]]                    # 스트리밍 청크 제너레이터 — JSON 직렬화 불가, 절대 영속화 금지


class DPartAnswerSnapshot(BaseModel):
    """복원용으로 저장하는 완성된 D 답변 1턴. 프론트 reduceDAnswer가 스트림으로 누적하는 것과
    같은 필드 구성이라, 사이드바에서 다시 열면 라이브 턴과 동일하게 렌더된다.
    (평문은 messages 테이블에도 있지만, 판정배지·인용카드·용어까지 살리려면 구조를 보존해야 한다.)"""
    user_input: str
    text: str = ""
    citations: list[dict] = Field(default_factory=list)
    judgment: Optional[str] = None
    appendix: str = ""
    disclaimer: str = ""
    terms: list[dict] = Field(default_factory=list)
    answer_kind: Optional[str] = None


class DPartSessionState(BaseModel):
    """conversations.state(JSONB)에 그대로 직렬화되는 턴 간 carryover 상태.
    다음 턴 시작 시 이 값으로 DPartGraphState의 대응 필드를 미리 채워 넣습니다.
    저장: state.model_dump(mode="json") / 로드: DPartSessionState.model_validate(raw_dict)
    """
    persona: Optional[str] = None
    situation: Optional[SituationState] = None
    victim_slots: VictimRequirementSlots = Field(default_factory=VictimRequirementSlots)
    victim_judgment: Optional[VictimJudgment] = None
    victim_fallback: bool = False
    victim_flow_closed: bool = False
    victim_check_attempts: int = 0
    victim_pending_slot: Optional[str] = None
    awaiting_relief_confirmation: bool = False
    # 캐리오버가 아니라 복원용 누적 이력 — 사이드바 재열람 전용. graph_input에는 넣지 않는다
    # (그래프는 이전 답변 텍스트가 아니라 carryover 상태만 본다). d_part 라우트가 매 턴 append한다.
    turn_history: list[DPartAnswerSnapshot] = Field(default_factory=list)
