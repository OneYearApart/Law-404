# 미인지형 판별 프롬프트 (초안)

사용자의 상황 서술을 아래 전세사기피해자법 요건 슬롯에 매핑하세요.

1. 전입신고 + 확정일자 여부
2. 보증금 5억 이하 여부 (최대 7억 상향 가능)
3. 2인 이상 피해(예상) 여부
4. 반환의도 없음을 의심할 상당한 이유

각 슬롯에 대해 [충족 / 불충족 / 불명확] 중 하나로 판정하고, 근거를 함께 제시하세요.
단정적 판단("됩니다/안됩니다") 금지 — 높음/있음/추가확인 3단계로 표현하세요.

이미 채워진 기존 슬롯 값이 함께 주어지면, 이번 발화에서 새로 확인된 내용만 갱신하고 나머지는 기존 값을 유지하세요.

경공매(공매/경매)가 이미 완료됐다는 언급이 있으면 auction_completed를 true로, 아니면 false로 판정하세요.

## 응답 형식

아래 JSON 형식으로만 응답하세요. 다른 텍스트를 덧붙이지 마세요. 판정 못한 슬롯은 "unclear"로 표기하세요.

```json
{
  "moved_in_and_fixed_date": "filled",
  "deposit_under_limit": "unfilled",
  "multiple_victims": "unclear",
  "no_intent_to_return": "filled",
  "multiple_victims_reason": "근거 텍스트 또는 null",
  "auction_completed": false
}
```
