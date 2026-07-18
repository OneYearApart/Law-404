# D파트 평가 골든셋

D파트 파이프라인의 품질을 숫자로 재기 위한 라벨 데이터셋. 기존 `tests/d_part/`는 전부
monkeypatch 기반 결정론적 단위테스트라 **실제 LLM 출력 품질(라우팅 정확도, 검색 적합도,
인용 충실도)을 재는 장치가 하나도 없었다.** 그 공백을 메우는 자산이다.

두 벌이 있다 — 라우팅(`routing_golden.jsonl`)과 피해자 판정(`victim_golden.json`).

> ⚠️ **`temperature=0`은 완전한 재현성을 주지 않는다.** 분류·추출 경로의 온도는 고정했지만
> (`app/llm/d_part.py::STRUCTURED_TEMPERATURE`) OpenAI는 seed 없이 완전 재현을 보장하지 않는다.
> 실제로 판정 골든셋의 경계 케이스 하나가 실행마다 `unclear`/`unfilled` 사이를 오간다.
> **수치를 인용할 때는 몇 회 실행의 어떤 값인지 함께 적을 것.**

## 왜 라우팅부터인가

D파트는 supervisor가 판별한 상황모델에서 5개 경로가 갈리고, 경로를 틀리면 그 뒤 검색·프롬프트·
지원절차 부착이 전부 어긋난다. 즉 **라우팅은 파이프라인 품질의 상한**이다. 게다가

- 턴당 LLM 호출 1회라 전체 셋을 돌려도 싸고 빠르다
- 라벨링에 법률 전문성이 필요 없다(13개 항목·특수 4종 정의가 기획서에 고정돼 있다)
- 개선 레버가 `prompts/supervisor.md` 한 곳이라 before/after 비교가 깔끔하다

검색 적합도(Recall@k)와 인용 충실도(groundedness)는 정답 조문 id를 달아야 해서 별도 셋으로 뺀다.

## 파일

| 경로 | 내용 |
|---|---|
| `routing_golden.jsonl` | 라우팅 골든셋 42케이스 (한 줄 = 한 케이스) |
| `victim_golden.json` | 피해자 판정 골든셋 8시나리오 / 35턴 (멀티턴이라 중첩 JSON) |
| `results/*.json` | `--run` 실행 결과(지표 + 케이스별 예측). 재생성 가능한 산출물이라 git에 넣지 않는다 |

## 판정 골든셋 (`victim_golden.json`)

라우팅이 "문 앞까지 제대로 도착하는가"를 잰다면 이건 "문 안에서 제대로 판정하는가"를 잰다.
**D파트에서 가장 위험한 출력**이다 — 사람에게 전세사기피해자법 요건 충족 가능성을 말하는 경로다.

여기서도 **LLM이 하는 일은 슬롯 추출 하나뿐**이다. 병합(`_merge_slots`), 다음질문 선택
(`_unresolved_required_slots`), 최종판정(`_compute_judgment`), fallback·제외 게이트는 전부
결정론적 코드다. 그래서 라벨은 각 턴이 끝난 시점의 **병합된 슬롯 상태**로 달고, 결정론 코드는
채점 함수로 쓴다(라우팅과 같은 원리).

턴 간에는 `DPartSessionState`가 실제로 넘기는 필드만 이어받는다 — 전체 state를 그대로 넘기면
`final_answer`가 남아 노드가 조기 return하고 실제 대화와 다른 것을 측정하게 된다.

주지표는 **최종 판정 정확도**. 보조로 종결 형태(판정/제외/폴백), 슬롯 정확도, 다음질문 정확도,
`auction_completed` 정확도를 낸다. 여기에 더해 **부당 제외 건수**를 따로 센다 — 구제수단이 없는데
'제외'로 끝나면 진짜 피해자를 지원대상에서 떨어뜨리는 사고라, 다른 수치가 좋아도 0이 아니면 실패다.

시나리오는 표준 충족(높음) / 슬롯④ 함정 / 경공매 면제 / 구제수단 제외 / 모호응답 재질문 /
폴백 / 한도초과 / 맥락의존 단답 8종. `unfilled`(확인했고 미충족 → 진행)와 `unclear`(미해결 →
재질문)의 구분이 이 셋의 핵심 축이다.

## 스키마

한 줄이 한 케이스. `_comment` 키만 있는 줄은 파일 내 주석이라 로더가 건너뛴다.

```json
{
  "id": "hrd-001",
  "utterance": "친구가 전세사기 피해자로 인정받았는데 저도 비슷한 상황일까요",
  "recognized": false,
  "risk_signals": [],
  "topic": null,
  "special_case": null,
  "route": "open_qa",
  "note": "3인칭 인정을 화자 본인의 recognized=true로 오판하는지"
}
```

**라벨은 `_infer_special_case_from_topic` 정규화를 거친 뒤의 값이다.** 정규화와 `route()`는
결정론적 코드라 평가 대상이 아니라 채점 함수의 일부다. 그래서 `spc-005`처럼 겹치는 발화는
LLM이 `special_case`를 안 채워도 topic에서 규칙으로 채워지는 것이 정답이다.

`route`는 나머지 네 축에서 파생되는 값이라 중복이지만, 사람이 읽을 때 의도가 바로 보이라고
같이 적는다. `--validate`가 이 둘의 불일치를 잡는다.

### id 접두어

| 접두어 | 수 | 무엇을 재는가 |
|---|---|---|
| `gen-` | 13 | 13개 항목 매칭 → `general_scenario` |
| `spc-` | 6 | 인지형 특수 4종 → `special_cases` |
| `vic-` | 7 | 위험신호 검출 → `victim_check` |
| `rec-` | 4 | 인정받았으나 4종·13항목 밖 → `recognized_general` |
| `oqa-` | 4 | 도메인 내 일반 질의 → `open_qa` |
| `neg-` | 4 | 과잉검출 방지(무관 발화, 인사말, 약한 불만) |
| `hrd-` | 4 | 적대적 케이스(3인칭 인정, 신청≠인정, 구제수단 보유) |

`gen-`/`spc-` 및 `vic-006`은 **대조쌍**으로 설계됐다 — 같은 상황 서술에 인정 여부만 다르게 줘서
`recognized` 축이 실제로 분기를 정하는지 본다(gen-003↔spc-003, gen-005↔spc-002, gen-006↔spc-004,
spc-001↔vic-006).

## 사용

```bash
# 라벨 무결성만 검사 — API 호출 없음. 골든셋 수정 시 항상 먼저 돌린다
python -X utf8 scripts/eval_d_part_routing.py --validate

# 실측(과금). LANGSMITH_TRACING=true면 케이스별 트레이스가 LangSmith에 남는다
python -X utf8 scripts/eval_d_part_routing.py --run

# 일부만
python -X utf8 scripts/eval_d_part_routing.py --run --only hrd,neg
```

주지표는 **경로 정확도**. 보조로 `recognized` 정확도, `topic`/`special_case` 정확일치,
`risk_signals` 마이크로 F1, 지연 p50/p95를 낸다. `risk_signals`는 다중 라벨이고 대부분의
케이스가 빈 배열이라 정확도로 재면 "아무것도 검출 안 함"이 고득점을 받는다 — 그래서 F1을 쓴다.

## 알려진 미결 케이스

**`hrd-004`** — "다른 세입자도 피해를 봤다고 들었어요"는 13개 항목의 중-⑤(조기경보)와 위험신호
`다수피해`가 같은 발화를 가리킨다. `route()`가 `risk_signals`를 `topic`보다 먼저 보므로 현행
동작은 `victim_check`이고 라벨도 거기 맞췄지만, 13개 항목 기획 의도는 `general_scenario`다.
**어느 쪽이 옳은지는 도메인 판단이 필요하다** — 라벨을 바꾸든 `route()`를 바꾸든 결정 전까지
이 케이스의 정오는 지표로 읽지 말 것.
