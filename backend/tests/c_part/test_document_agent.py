import pytest
import pytest_asyncio

from langchain_openai import ChatOpenAI
from app.core.config import settings
from app.graph.parts.c_part.agents.document_agent import (
    DocumentAgent,
    REQUIRED_FIELDS,
)


@pytest_asyncio.fixture
async def agent():

    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=0.2,
        api_key=settings.OPENAI_API_KEY,
        max_retries=3,
        timeout=60,
    )
    return DocumentAgent(llm)


# ════════════════════════════════════════════════════════════════════════════════
# 【1】정보 추출
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestExtractInfo:
    """정보 추출 테스트"""

    async def test_추출_이름_두개(self, agent):

        result = await agent.extract_info(
            user_message="저는 홍길동이고 집주인은 김철수예요",
            collected={},
        )

        assert result.get("tenant_name") == "홍길동", \
            f"임차인 이름 추출 실패: {result}"
        assert result.get("landlord_name") == "김철수", \
            f"임대인 이름 추출 실패: {result}"

        print(f"\n✅ 추출: {result}")

    async def test_추출_금액(self, agent):

        result = await agent.extract_info(
            user_message="보증금은 5천만원이에요",
            collected={},
        )

        assert result.get("deposit") == 50_000_000, \
            f"금액 추출 실패: {result.get('deposit')} (기대: 50000000)"

        print(f"\n✅ 보증금: {result['deposit']:,}원")

    async def test_추출_날짜(self, agent):

        result = await agent.extract_info(
            user_message="계약은 2026년 3월 31일에 끝났어요",
            collected={},
        )

        lease_end = result.get("lease_end", "")
        assert "2026" in str(lease_end) and "03" in str(lease_end), \
            f"날짜 추출 실패: {lease_end}"

        print(f"\n✅ 종료일: {lease_end}")

    async def test_기존정보_유지(self, agent):

        collected = {
            "tenant_name": "홍길동",
            "landlord_name": "김철수",
        }

        result = await agent.extract_info(
            user_message="보증금은 3천만원이에요",
            collected=collected,
        )

        # 기존 정보가 남아있는가
        assert result.get("tenant_name") == "홍길동", "기존 정보가 사라짐!"
        assert result.get("landlord_name") == "김철수", "기존 정보가 사라짐!"

        # 새 정보가 추가됐는가
        assert result.get("deposit") == 30_000_000

        print(f"\n✅ 병합 성공: {result}")

    async def test_정보없는_메시지(self, agent):

        result = await agent.extract_info(
            user_message="내용증명 써주세요",
            collected={},
        )

        # 아무것도 추출되지 않아야 정상
        assert len(result) == 0, f"없는 정보를 지어냈습니다: {result}"

        print(f"\n✅ 지어내지 않음")


# ════════════════════════════════════════════════════════════════════════════════
# 【2】되묻기
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestAskNext:
    """되묻기 테스트"""

    async def test_첫_질문(self, agent):
        """
        【테스트】정보가 아예 없을 때 첫 질문

        REQUIRED_FIELDS의 첫 항목(tenant_name)을 물어봐야 합니다.
        """
        missing = agent.get_missing_fields({})

        assert len(missing) == len(REQUIRED_FIELDS), \
            "빈 상태면 모든 필수 항목이 missing이어야 함"
        assert missing[0] == "tenant_name", \
            f"첫 질문이 tenant_name이어야 함: {missing[0]}"

        question = await agent.ask_next({}, missing)

        assert len(question) > 0
        print(f"\n✅ 첫 질문:\n{question}")

    async def test_중간_질문(self, agent):
        """
        【테스트】일부만 채워졌을 때

        이름 2개는 있고, 주소가 없는 상황
        → 임대인 주소를 물어봐야 함
        """
        collected = {
            "tenant_name": "홍길동",
            "landlord_name": "김철수",
        }

        missing = agent.get_missing_fields(collected)

        assert "tenant_name" not in missing
        assert "landlord_name" not in missing
        assert "landlord_address" in missing

        question = await agent.ask_next(collected, missing)

        print(f"\n✅ 중간 질문:\n{question}")


# ════════════════════════════════════════════════════════════════════════════════
# 【3】문서 생성
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestGenerateDocument:
    """문서 생성 테스트"""

    async def test_문서_생성(self, agent):

        collected = {
            "tenant_name": "홍길동",
            "tenant_address": "서울시 강남구 테헤란로 123",
            "tenant_phone": "010-1234-5678",
            "landlord_name": "김철수",
            "landlord_address": "서울시 서초구 서초대로 456",
            "property_address": "서울시 강남구 테헤란로 123, 101동 202호",
            "lease_end": "2026-03-31",
            "deposit": 50_000_000,
        }

        document = await agent.generate_document(collected)

        print(f"\n{'='*70}")
        print("생성된 내용증명")
        print('='*70)
        print(document)
        print('='*70)

        # 【검증 1】필수 정보가 들어갔는가
        assert "홍길동" in document, "임차인 이름 누락"
        assert "김철수" in document, "임대인 이름 누락"
        assert "50,000,000" in document or "5천만" in document, "보증금 누락"

        # 【검증 2】법적 근거가 인용됐는가
        assert "제3조의2" in document or "주택임대차보호법" in document, \
            "법적 근거 누락"

        # 【검증 3】마크다운이 없는가
        assert "**" not in document, "마크다운 볼드가 남아있음"
        assert "##" not in document, "마크다운 헤더가 남아있음"

        # 【검증 4】과격한 표현이 없는가
        forbidden = ["고소", "가만두지", "각오"]
        for word in forbidden:
            assert word not in document, f"과격한 표현: {word}"


# ════════════════════════════════════════════════════════════════════════════════
# 【4】전체 대화 시뮬레이션  ← 가장 중요
# ════════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_전체_대화_시뮬레이션(agent):
    """
    【통합 테스트】처음부터 끝까지 대화 진행

    ⚠️ 이게 진짜 사용 시나리오입니다.
       프론트가 이대로 동작하게 됩니다.

    ⚠️ GPT를 10회 이상 호출합니다 (약 $0.02, 1~2분 소요).
    """
    print(f"\n{'='*70}")
    print("전체 대화 시뮬레이션")
    print('='*70)

    # 【시나리오】사용자가 순서대로 답하는 상황
    user_messages = [
        "내용증명 써주세요",
        "저는 홍길동이고 집주인은 김철수예요",
        "집주인 주소는 서울시 서초구 서초대로 456이에요",
        "제가 살던 집은 서울시 강남구 테헤란로 123, 101동 202호예요",
        "계약은 2026년 3월 31일에 끝났어요",
        "보증금은 5천만원이에요",
    ]

    collected = {}
    turn = 0

    for msg in user_messages:
        turn += 1
        print(f"\n{'─'*70}")
        print(f"[턴 {turn}] 사용자: {msg}")
        print('─'*70)

        result = await agent.process(
            user_message=msg,
            collected=collected,
        )

        # 【중요】프론트가 collected를 들고 다니는 것을 시뮬레이션
        collected = result["collected"]

        print(f"진행률: {result['progress']:.0%} "
              f"({len(REQUIRED_FIELDS) - len(result['missing'])}"
              f"/{len(REQUIRED_FIELDS)})")

        if result["status"] == "need_more_info":
            print(f"\n에이전트: {result['next_question']}")
            print(f"\n아직 필요: {', '.join(result['missing_labels'])}")

        elif result["status"] == "complete":
            print(f"\n{'='*70}")
            print("✅ 문서 완성!")
            print('='*70)
            print(result["document"])
            print('='*70)

            # 【검증】
            assert result["document"], "문서가 비어있음"
            assert "홍길동" in result["document"]
            assert "김철수" in result["document"]
            assert result["progress"] == 1.0

            print(f"\n✅ 대화 {turn}턴 만에 문서 완성")
            return

    # 여기 오면 실패 (모든 메시지를 다 보냈는데도 문서가 안 나옴)
    pytest.fail(
        f"❌ {len(user_messages)}턴을 진행했는데도 문서가 완성되지 않았습니다.\n"
        f"   아직 부족: {result['missing_labels']}\n"
        f"   수집됨: {collected}"
    )