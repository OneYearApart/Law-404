"""
단위 33 — 동기 DB 호출이 threadpool로 오프로드돼 동시 요청이 직렬화되지 않는지 검증.

repository의 DB 함수는 동기 SessionLocal을 쓰므로, async 노드/SSE 스트리밍 중 직접
호출하면 이벤트 루프를 블로킹해 동시 요청이 사실상 직렬화된다. _threadpooled로 워커
스레드에 넘겨 루프를 놓아주는지(= 2건이 병렬로 도는지) 확인한다.
"""
import asyncio
import threading
import time

import pytest

from app.conversations.repository import _threadpooled


@pytest.mark.asyncio
async def test_threadpooled_offloads_to_worker_thread_and_runs_concurrently():
    sleep_s = 0.3

    @_threadpooled
    def blocking_db_call():
        time.sleep(sleep_s)  # 동기 DB 블록(SessionLocal 쿼리)을 흉내
        return threading.current_thread()

    start = time.perf_counter()
    thread_a, thread_b = await asyncio.gather(blocking_db_call(), blocking_db_call())
    elapsed = time.perf_counter() - start

    # 이벤트 루프(메인 스레드)가 아니라 워커 스레드에서 실행 → 루프를 블로킹하지 않음
    assert thread_a is not threading.main_thread()
    assert thread_b is not threading.main_thread()
    # 병렬이면 ~sleep_s, 직렬(이벤트 루프 블로킹)이면 ~2*sleep_s
    assert elapsed < sleep_s * 1.8
