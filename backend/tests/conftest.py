"""
【conftest.py】Pytest 설정 (asyncio 포함)

파일 위치: tests/conftest.py

역할:
- 모든 테스트에서 공통으로 사용할 설정
- asyncio 모드 설정
- 전역 fixture 정의
"""

import pytest
import pytest_asyncio

# ════════════════════════════════════════════════════════════════════════════════
# 【asyncio 설정】
# ════════════════════════════════════════════════════════════════════════════════

# 【pytest_asyncio_mode】asyncio 작동 모드 설정
#
# 옵션:
# - "auto": 자동 감지 (추천)
#   → @pytest.mark.asyncio 또는 async def 자동 인식
#   → 더 이상 수동 모드 설정 불필요
#
# - "strict": 엄격 모드
#   → @pytest.mark.asyncio 필수
#   → async def 자동 인식 안 함
#
pytest_asyncio_mode = "auto"


# ════════════════════════════════════════════════════════════════════════════════
# 【전역 Fixture】모든 테스트에서 사용 가능
# ════════════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def mock_llm():
    """
    【Mock LLM Fixture】

    역할:
    - 모든 테스트에서 사용할 수 있는 모의 LLM
    - 실제 API 호출 없이 테스트 가능
    - 속도가 매우 빠름

    사용 예:
    ```python
    async def test_something(mock_llm):
        # mock_llm을 사용한 테스트
    ```

    ⚠️ 주의:
    - 이 fixture는 선택사항
    - Phase 3는 실제 LLM이 필요하므로 사용 안 함
    - Phase 2 (Mock 테스트)에서 사용
    """
    from test_answer_generator import MockLLM

    return MockLLM(mode="safe")


# ════════════════════════════════════════════════════════════════════════════════
# 【Hook: 테스트 시작/종료】
# ════════════════════════════════════════════════════════════════════════════════


def pytest_configure(config):
    """
    【Hook: Pytest 설정 시작】

    역할:
    - Pytest 초기화 전에 실행
    - 커스텀 마커 등록, 설정값 초기화
    """
    # 【커스텀 마커 등록】
    config.addinivalue_line(
        "markers", "integration: Phase 3 통합 테스트 (실제 API 호출)"
    )
    config.addinivalue_line("markers", "unit: 단위 테스트 (Mock LLM 사용)")


def pytest_sessionstart(session):
    """
    【Hook: 테스트 세션 시작】

    역할:
    - 테스트 실행 직전에 한 번 실행
    - 환경 초기화, 디렉토리 생성 등
    """
    import os

    # 【테스트 결과 디렉토리 생성】
    os.makedirs("test_results/phase3", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    os.makedirs("logs", exist_ok=True)


def pytest_sessionfinish(session, exitstatus):
    """
    【Hook: 테스트 세션 종료】

    역할:
    - 모든 테스트 실행 후에 한 번 실행
    - 정리 작업, 최종 리포트 생성 등
    """
    print("\n" + "=" * 80)
    print("【테스트 세션 완료】")
    print("=" * 80)

    if exitstatus == 0:
        print("✅ 모든 테스트 통과!")
    else:
        print("❌ 일부 테스트 실패")

    print(f"테스트 결과: test_results/phase3/")
    print(f"리포트: reports/")
