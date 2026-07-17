"""
지원절차 액션플랜 큐레이션 텍스트 단일 정의처.

special_cases._SPECIAL_CASE_GUIDANCE / _disclaimer.DISCLAIMER와 동일하게, 절차·지원수단·기관
같은 '고정 출력'은 LLM 생성이 아니라 여기 정적 텍스트로 관리한다(종합문서 §14.1 "출력을
하드코딩하는 것은 맞다"). 환각 시 잘못된 절차 안내 사고로 직결되기 때문이다.

입도: 종합문서 §8.4가 지원절차 안내를 '개요 수준'으로 스코프한다 — 인지형 special_cases와
동일하게 지원수단 이름과 신청 가능성 안내까지만 두고, 상세 서류/양식은 관할 기관 안내로 넘긴다.

⚠️ 아래 문구/지원수단 적용요건은 구조 초안이다. 배포 전 최신 전세사기피해자법·시행령 및
국토교통부/HUG 공식 안내로 검수 확정할 것(기획서 §7). 문구는 finalize._BANNED_JUDGMENT_TERMS
(됩니다/확실합니다/틀림없/불가능합니다/보장합니다 등 단정 표현)를 쓰지 않고 special_cases
톤("권해드립니다")을 따른다. 면책조항은 finalize가 자동 첨부하므로 여기서 작성하지 않는다.

향후 special_cases가 이 상수를 공유 소스로 소비하도록 통합할 여지를 남긴다(기획서 §2.2, §6).
"""
from app.graph.parts.d_part.schemas import SlotStatus, VictimRequirementSlots

# 높음(High) — 신청 가능성 + 활용 지원수단 개요 (경공매 사전/사후 분기) --------------
_APPLY_STEP = (
    "■ 지금 확인·실행하실 점\n"
    "- 관할 시·도의 전세사기피해지원위원회에 피해자 결정을 신청하실 수 있습니다."
)
_SUPPORT_MEASURES_PRE_AUCTION = (
    "- 상황에 따라 우선매수권, 경·공매 유예, 조세채권 안분, 최우선변제, 금융지원 등을 "
    "활용하실 수 있는지 확인이 필요합니다."
)
_SUPPORT_MEASURES_POST_AUCTION = (
    "- 경·공매가 이미 진행된 상황이라면 배당요구·명도 단계에서 활용 가능한 절차를 "
    "관할 기관과 확인하시길 권해드립니다."
)

# 추가확인(NeedsConfirmation) — 미충족 요건 보완 안내 -----------------------
_CONFIRM_HEADER = "■ 재평가를 위해 확인·확보하실 점"
_SLOT_GAP_GUIDANCE = {
    "moved_in_and_fixed_date": "전입신고·확정일자(또는 임차권등기·전세권 설정) 확보 여부를 확인하시길 권해드립니다.",
    "deposit_under_limit": "보증금 액수가 지원 한도 내인지 확인이 필요합니다.",
    "multiple_victims": "같은 임대인의 다른 피해 정황(파산·회생, 경·공매 개시, 압류 등)을 확인하시길 권해드립니다.",
    "no_intent_to_return": "임대인의 반환의도 부재를 의심할 만한 구체적 정황·자료를 확보하시길 권해드립니다.",
}

# 공통 (높음/추가확인 모두 첨부) -------------------------------------------
_PROTECTIVE_STEPS = (
    "■ 시점을 놓치지 않도록 유의하실 점\n"
    "- 퇴거 전 임차권등기명령을 통해 대항력·우선변제권을 유지하시길 권해드립니다.\n"
    "- 배당요구 종기 등 기한은 관할 법원·기관에서 확인하시길 권해드립니다."
)
_CONTACTS = (
    "■ 상담·문의\n"
    "- 전세사기피해지원 통합 안내, HUG, 대한법률구조공단 등 전문기관 상담을 권해드립니다."
)

_SLOT_ORDER = ("moved_in_and_fixed_date", "deposit_under_limit", "multiple_victims", "no_intent_to_return")


def unfilled_slot_lines(slots: VictimRequirementSlots) -> list[str]:
    """추가확인 판정에서 UNFILLED로 남은 요건에 대한 보완 안내 문구 목록.

    (판정 도달 시점이라 슬롯은 FILLED/UNFILLED로 해소돼 있고 UNCLEAR는 없다고 가정 —
    victim_check._unresolved_required_slots가 UNCLEAR/None을 먼저 걸러 슬롯 질문으로
    되돌리기 때문에, 판정이 확정된 턴에는 필수 슬롯이 FILLED/UNFILLED만 남는다.)
    """
    return [
        f"- {_SLOT_GAP_GUIDANCE[name]}"
        for name in _SLOT_ORDER
        if getattr(slots, name) == SlotStatus.UNFILLED
    ]
