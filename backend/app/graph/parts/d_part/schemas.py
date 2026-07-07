"""
전세사기피해자법 요건 슬롯 정의.

요건 슬롯 목록은 전세사기피해자법 조문 확인 후 확정 예정.
현재까지 확인된 제3조 피해자 요건 4가지:
  ① 전입신고 + 확정일자
  ② 보증금 5억 이하 (최대 7억 상향 가능)
  ③ 2인 이상 피해(예상)
  ④ 반환의도 없음을 의심할 상당한 이유
"""
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class SlotStatus(str, Enum):
    FILLED = "filled"
    UNFILLED = "unfilled"
    UNCLEAR = "unclear"


class VictimRequirementSlots(BaseModel):
    moved_in_and_fixed_date: Optional[SlotStatus] = None      # ① 전입신고+확정일자
    deposit_under_limit: Optional[SlotStatus] = None            # ② 보증금 한도
    multiple_victims: Optional[SlotStatus] = None                # ③ 2인 이상 피해
    no_intent_to_return: Optional[SlotStatus] = None             # ④ 반환의도 없음 의심
