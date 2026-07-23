"""
대화 요약용 Ollama 모델 비교 스크립트 (qwen2.5 vs exaone).

로컬 Ollama가 떠 있는 상태에서 수동 실행:
    python scripts/bench_ollama_summary.py

응답 속도/품질을 눈으로 비교해 .env의 OLLAMA_SUMMARY_MODEL, SUMMARY_TRIGGER_TURNS를 정하는 용도.
프로덕션 코드 경로에는 포함되지 않음.
"""

import asyncio
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from app.local_model.models.common.interface import PROMPT_TEMPLATE
from app.local_model.models.common.model_loader import generate

CANDIDATE_MODELS = ["exaone3.5:latest", "qwen2.5:3b-instruct"]

SAMPLE_CONVERSATION = [
    "user: 안녕하세요, 전세 계약 관련해서 문의드리고 싶어요.",
    "assistant: 네, 어떤 상황이신지 말씀해 주시겠어요?",
    "user: 계약 만료가 한 달 남았는데 집주인이 보증금을 안 돌려준다고 해요.",
    "assistant: 임대차보호법상 임차인은 보증금 반환 지연에 대해 지연손해금을 청구할 수 있습니다. 관련 요건을 확인해보겠습니다.",
]


async def bench_model(model: str) -> None:
    prompt = PROMPT_TEMPLATE.format(conversation="\n".join(SAMPLE_CONVERSATION))
    start = time.perf_counter()
    try:
        title = await generate(prompt, model=model)
    except Exception as e:
        print(f"[{model}] 실패: {e}")
        return
    elapsed = time.perf_counter() - start
    print(f"[{model}] {elapsed:.2f}s -> {title!r}")


async def main() -> None:
    for model in CANDIDATE_MODELS:
        await bench_model(model)


if __name__ == "__main__":
    asyncio.run(main())
