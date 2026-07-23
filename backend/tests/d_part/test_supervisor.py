"""
supervisor 노드 테스트 (DB 접근 없는 순수 로직).
call_supervisor(LLM tool calling)는 monkeypatch로 흉내낸다.
"""

import pytest

from app.graph.parts.d_part.nodes import supervisor
from app.graph.parts.d_part.nodes.supervisor import (
    interview_in_progress,
    route,
    run_supervisor,
    situation_from_supervisor_result,
)
from app.graph.parts.d_part.schemas import (
    SituationState,
    SlotStatus,
    VictimJudgment,
    VictimRequirementSlots,
)


async def _unreachable_call_supervisor(user_input: str) -> dict:
    raise AssertionError("진행 중인 흐름이 있을 땐 call_supervisor가 호출되면 안 된다")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state",
    [
        {"awaiting_relief_confirmation": True},
        {
            "victim_slots": VictimRequirementSlots(
                moved_in_and_fixed_date=SlotStatus.FILLED
            )
        },
    ],
)
async def test_in_progress_victim_check_skips_llm_call(monkeypatch, state):
    monkeypatch.setattr(
        supervisor.llm_d_part, "call_supervisor", _unreachable_call_supervisor
    )
    state = {**state, "user_input": "2억이에요"}

    await run_supervisor(state)

    assert interview_in_progress(state) is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "closed_state",
    [
        # 판정 확정
        {"victim_judgment": VictimJudgment.HIGH, "victim_flow_closed": True},
        # 지원대상 제외(victim_judgment는 None으로 남는다)
        {
            "victim_flow_closed": True,
            "victim_slots": VictimRequirementSlots(
                moved_in_and_fixed_date=SlotStatus.FILLED, has_relief_measure=True
            ),
        },
        # fallback
        {"victim_fallback": True, "victim_flow_closed": True},
    ],
)
async def test_closed_victim_flow_is_reclassified(monkeypatch, closed_state):
    """인터뷰가 종결된 뒤엔 슬롯/판정 값이 세션에 남아 있어도 이번 턴 발화를 정상 재분류해야 한다
    (종결 후 모든 후속 턴이 victim_check로 영구히 고정되던 버그의 회귀 테스트)."""

    async def _fake(user_input: str) -> dict:
        return {"recognized": False, "risk_signals": []}

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake)
    state = {**closed_state, "user_input": "전세보증보험은 언제 가입하나요?"}

    result = await run_supervisor(state)

    assert interview_in_progress(result) is False  # 재분류 대상
    assert route(result["situation"]) == "open_qa"


@pytest.mark.asyncio
async def test_victim_interview_category_routes_to_victim_check(monkeypatch):
    async def _fake(user_input: str) -> dict:
        return {"recognized": False, "risk_signals": ["보증금미반환"]}

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake)

    result = await run_supervisor({"user_input": "보증금을 못 받고 있어요"})

    assert route(result["situation"]) == "victim_check"


@pytest.mark.asyncio
async def test_special_case_situation_routes_to_special_cases(monkeypatch):
    async def _fake(user_input: str) -> dict:
        # 실호출이 이 발화에서 실제로 뱉는 모양 — risk_signals는 6종 enum에 문자 매칭되므로
        # "신탁을 걸어놨다"엔 아무것도 안 걸려 빈 배열로 온다
        return {"recognized": True, "risk_signals": [], "special_case": "신탁사기"}

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake)

    result = await run_supervisor(
        {"user_input": "신탁 등기가 되어 있고 이미 피해자로 인정받았어요"}
    )

    assert route(result["situation"]) == "special_cases"
    assert result["situation"].special_case == "신탁사기"


@pytest.mark.asyncio
async def test_general_topic_situation_routes_to_general_scenario(monkeypatch):
    async def _fake(user_input: str) -> dict:
        return {
            "recognized": False,
            "risk_signals": [],
            "topic": "전-①등기부등본_위험신호",
        }

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake)

    result = await run_supervisor(
        {"user_input": "등기부등본에 근저당이 많이 잡혀있어서 불안해요"}
    )

    assert route(result["situation"]) == "general_scenario"
    assert result["situation"].topic == "전-①등기부등본_위험신호"


@pytest.mark.asyncio
async def test_open_qa_category_routes_to_open_qa(monkeypatch):
    async def _fake(user_input: str) -> dict:
        return {"recognized": False, "risk_signals": []}

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake)

    result = await run_supervisor(
        {"user_input": "보증금 반환청구 소송은 어떻게 진행하나요"}
    )

    assert route(result["situation"]) == "open_qa"


@pytest.mark.asyncio
async def test_situation_is_filled_per_axis(monkeypatch):
    """축이 각각 독립적으로 situation에 담기는지 — 특히 recognized와 topic이 공존할 수 있어야
    한다. 카테고리 하나로 압축하던 때는 이 발화에서 인지여부가 topic에 가려져 사라졌다."""

    async def _fake(user_input: str) -> dict:
        return {
            "recognized": True,
            "risk_signals": ["경공매개시", "다수피해"],
            "topic": "전-③다가구_선순위보증금",
            "special_case": "다가구주택",
        }

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake)

    result = await run_supervisor(
        {"user_input": "피해자로 인정받았고 다가구 선순위가 궁금해요"}
    )

    situation = result["situation"]
    assert situation.recognized is True
    assert situation.risk_signals == ["경공매개시", "다수피해"]
    assert situation.topic == "전-③다가구_선순위보증금"
    assert situation.special_case == "다가구주택"


@pytest.mark.asyncio
async def test_absent_axes_become_none_not_empty_string(monkeypatch):
    """해당 없는 축은 tool 인자에서 아예 빠져 온다(스키마 required가 아님)."""

    async def _fake(user_input: str) -> dict:
        return {"recognized": False, "risk_signals": []}

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake)

    situation = (
        await run_supervisor({"user_input": "전세 계약 갱신은 어떻게 하나요"})
    )["situation"]

    assert situation.topic is None
    assert situation.special_case is None
    assert situation.risk_signals == []


@pytest.mark.parametrize(
    "situation, expected",
    [
        # 위험신호 있음 + 미인지 → 요건 인터뷰
        (
            SituationState(recognized=False, risk_signals=["보증금미반환"]),
            "victim_check",
        ),
        # 위험신호 있음 + 인지 + 특수 4종 → 특수상황
        (
            SituationState(
                recognized=True,
                risk_signals=["임대인사망파산"],
                special_case="임대인 사망/파산",
            ),
            "special_cases",
        ),
        # 인지 + 특수 4종인데 위험신호가 안 잡힌 경우 → 여전히 특수상황.
        # 위험신호를 요구하면 "인정받았고 신탁 걸려있다" 류 발화가 전부 자유질의로 새어나간다
        # (6종 enum에 문자로 안 걸려 빈 배열이 오기 때문 — 실호출로 확인된 회귀).
        (
            SituationState(recognized=True, risk_signals=[], special_case="신탁사기"),
            "special_cases",
        ),
        # 위험신호 없음 + topic → 일반 시나리오
        (
            SituationState(recognized=False, topic="전-①등기부등본_위험신호"),
            "general_scenario",
        ),
        # 아무 축도 안 걸림 → 자유질의
        (SituationState(recognized=False), "open_qa"),
        # 인지 + topic → 일반 시나리오 그대로. 인지 여부를 이유로 recognized_general(전체 검색)로
        # 보내면 항목별 topic_tag 정조준 검색을 버리게 된다 — 인지형 톤은 프롬프트가 담당한다.
        (
            SituationState(recognized=True, topic="후-②이중계약_배당순위"),
            "general_scenario",
        ),
    ],
)
def test_route_preserves_existing_paths(situation, expected):
    """라우팅을 순수함수로 옮긴 뒤에도 기존 4경로의 결과가 그대로인지 — 무회귀의 증명."""
    assert route(situation) == expected


@pytest.mark.parametrize(
    "topic, expected_special_case",
    [
        ("전-③다가구_선순위보증금", "다가구주택"),
        ("전-⑤신탁사기", "신탁사기"),
        ("전-⑥공인중개사_허위고지", "공인중개사 허위고지"),
        ("전-①등기부등본_위험신호", None),  # 특수 4종과 겹치지 않는 주제는 그대로 둔다
    ],
)
def test_recognized_user_topic_infers_overlapping_special_case(
    topic, expected_special_case
):
    """전-③/⑤/⑥은 특수 4종과 같은 상황의 '인정 전' 판본이라, 인정받은 사용자면 특수상황이다.
    모델이 이 겹침에서 special_case를 채울지 말지 일관되지 않아 규칙으로 정한다(실호출로 확인)."""
    result = situation_from_supervisor_result(
        {"recognized": True, "risk_signals": [], "topic": topic}
    )

    assert result.special_case == expected_special_case


def test_unrecognized_user_topic_does_not_infer_special_case():
    """인정 전이면 같은 주제라도 특수상황이 아니다 — 그게 두 목록을 가르는 축이다."""
    result = situation_from_supervisor_result(
        {"recognized": False, "risk_signals": [], "topic": "전-③다가구_선순위보증금"}
    )

    assert result.special_case is None
    assert route(result) == "general_scenario"


@pytest.mark.parametrize(
    "special_case, expected_topic",
    [
        ("다가구주택", "전-③다가구_선순위보증금"),
        ("신탁사기", "전-⑤신탁사기"),
        ("공인중개사 허위고지", "전-⑥공인중개사_허위고지"),
        (
            "임대인 사망/파산",
            None,
        ),  # 검색 태그가 topic 키가 아니라 대응되는 13개 항목이 없다
    ],
)
def test_unrecognized_user_special_case_infers_overlapping_topic(
    special_case, expected_topic
):
    """겹침 매핑은 양방향이어야 한다. route()는 special_case를 recognized 블록 안에서만 읽으므로,
    미인지형인데 모델이 topic 대신 special_case만 채우면 상황을 정확히 판별하고도 open_qa로
    떨어진다 — "이 집이 신탁사 소유라고 하던데요"에서 실측(골든셋 gen-005). 그러면 topic_tag
    정조준 검색 대신 광역 검색을 받아 근거의 질까지 떨어진다."""
    result = situation_from_supervisor_result(
        {"recognized": False, "risk_signals": [], "special_case": special_case}
    )

    assert result.topic == expected_topic
    assert route(result) == ("general_scenario" if expected_topic else "open_qa")


def test_model_supplied_special_case_wins_over_inference():
    """모델이 이미 판단했으면 그 값을 존중한다 — 추론은 빈 자리를 메우는 용도다."""
    result = situation_from_supervisor_result(
        {
            "recognized": True,
            "risk_signals": [],
            "topic": "전-③다가구_선순위보증금",
            "special_case": "신탁사기",
        }
    )

    assert result.special_case == "신탁사기"


def test_out_of_vocabulary_axis_values_are_dropped():
    """tool calling은 strict가 아니면 enum을 강제하지 않는다 — 모델이 topic 키를 special_case
    자리에 넣는 걸 실호출로 확인했다. 라우팅이 그대로 믿고 분기하므로 모르는 값은 버린다."""
    result = situation_from_supervisor_result(
        {
            "recognized": False,
            "risk_signals": ["보증금미반환", "그런거_없음"],
            "topic": "존재하지_않는_주제",
            "special_case": "전-①등기부등본_위험신호",  # topic 키가 여기로 새어들어온 실제 사례
        }
    )

    assert result.topic is None
    assert result.special_case is None
    assert result.risk_signals == ["보증금미반환"]


@pytest.mark.parametrize(
    "situation",
    [
        # 위험신호를 말한 인정 피해자
        SituationState(recognized=True, risk_signals=["보증금미반환"]),
        # 상황을 특정하지 않고 인정 사실만 밝힌 경우("인정받았는데 이제 뭘 해야 하나요")
        SituationState(recognized=True, risk_signals=[]),
    ],
)
def test_recognized_non_special_victim_gets_own_path(situation):
    """인정받았지만 특수 4종도 13개 항목도 아닌 피해자는 자유질의(open_qa)로 떨어졌다 —
    사용자 상황을 모른다고 전제한 일반론 답변을 받고 인지형 지원절차 개요도 못 받는 빈칸이었다."""
    assert route(situation) == "recognized_general"


@pytest.mark.asyncio
async def test_recognized_general_routes_without_matched_category(monkeypatch):
    """전용 경로로 가는 턴은 topic도 special_case도 비어 있다 — 그게 이 경로의 정의다."""

    async def _fake(user_input: str) -> dict:
        return {"recognized": True, "risk_signals": ["보증금미반환"]}

    monkeypatch.setattr(supervisor.llm_d_part, "call_supervisor", _fake)

    result = await run_supervisor(
        {"user_input": "피해자로 인정받았는데 보증금을 아직 못 받았어요"}
    )

    assert route(result["situation"]) == "recognized_general"
    assert result["situation"].special_case is None
    assert result["situation"].topic is None
