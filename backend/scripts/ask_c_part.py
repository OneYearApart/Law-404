
import asyncio
import sys
import time
import logging
from pathlib import Path

# ════════════════════════════════════════════════════════════════════════════════
# 【경로 설정】프로젝트 루트를 Python 경로에 추가
# ════════════════════════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 【로그 설정】
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)

# 【import】이제 app을 찾을 수 있습니다
from app.graph.parts.c_part.builder import get_c_part_graph
from app.rag.retrievers.c_part import CPartRetriever


# ════════════════════════════════════════════════════════════════════════════════
# 【헬퍼】검색 결과 변환
# ════════════════════════════════════════════════════════════════════════════════


def convert_search_results(chunks: list) -> dict:
    """list[RetrievedChunk] → {"statutes": [...], "precedents": [...]}"""
    statutes = []
    precedents = []

    for chunk in chunks:
        if chunk.source_type == "statute":
            article_num = chunk.statute_number or ""
            if chunk.statute_branch:
                article_num = f"{article_num}조의{chunk.statute_branch}"
            else:
                article_num = f"{article_num}조"

            statutes.append({
                "article_number": article_num,
                "title": chunk.statute_title or "",
                "content": chunk.content,
                "similarity": chunk.similarity,
            })

        elif chunk.source_type == "precedent":
            precedents.append({
                "case_number": chunk.case_number or "",
                "case_name": chunk.case_name or "",
                "case_date": str(chunk.case_date) if chunk.case_date else "",
                "content": chunk.content,
                "similarity": chunk.similarity,
                "court_level": 0,
                "case_year": "",
                "ruling_type": "",
            })

    return {"statutes": statutes, "precedents": precedents}


# ════════════════════════════════════════════════════════════════════════════════
# 【출력】답변을 보기 좋게 콘솔에 표시
# ════════════════════════════════════════════════════════════════════════════════

def print_divider(title: str = "", char: str = "═", width: int = 78):
    """구분선 출력"""
    if title:
        print(f"\n{char * width}")
        print(f"  {title}")
        print(f"{char * width}")
    else:
        print(char * width)


def print_answer(answer: dict, elapsed: float):
    """
    【출력】답변 전체를 콘솔에 표시

    ⚠️ 순서가 중요합니다.
       사용자가 실제로 읽는 순서대로 출력합니다:
       상황 진단 → 법 조문 → 판례 → 절차 → 비용 → 반박 → FAQ
    """

    # ────────────────────────────────────────────────────────────────────
    # 【Off-topic】카테고리3 범위 밖이면 안내 메시지만
    # ────────────────────────────────────────────────────────────────────
    if answer.get("is_off_topic"):
        print_divider("⚠️  관련 없는 질문", "─")
        print()
        print(answer.get("message", ""))
        print()
        print(f"⏱️  {elapsed:.1f}초 (GPT 1회 호출 — 7단계 건너뜀)")
        return

    # ────────────────────────────────────────────────────────────────────
    # 【메타 정보】먼저 요약을 보여줍니다
    # ────────────────────────────────────────────────────────────────────
    print_divider("📊 요약")

    confidence = answer.get("confidence_score", 0)

    # 신뢰도를 시각적으로
    bar_filled = int(confidence * 20)
    bar = "█" * bar_filled + "░" * (20 - bar_filled)

    print(f"\n  신뢰도  [{bar}] {confidence:.2f}")
    print(f"  소요시간 {elapsed:.1f}초")

    deposit = answer.get("deposit_amount")
    if deposit:
        print(f"  보증금  {deposit:,}원 (질문에서 추출 → 비용 계산에 사용)")
    else:
        print(f"  보증금  미확인 (질문에 금액이 없음 → 비용 계산 생략)")

    faq_count = len(answer.get("follow_up_questions", []))
    print(f"  FAQ    {faq_count}개")

    # ────────────────────────────────────────────────────────────────────
    # 【각 섹션】사용자가 읽는 순서대로
    # ────────────────────────────────────────────────────────────────────
    sections = [
        ("situation", "1️⃣  상황 진단"),
        ("legal_basis", "2️⃣  관련 법 조문"),
        ("precedents", "3️⃣  관련 판례"),
        ("action_steps", "4️⃣  행동 절차"),
        ("expected_cost", "5️⃣  예상 비용"),
        ("anticipated_disputes", "6️⃣  임대인 반박 & 대응"),
    ]

    for key, title in sections:
        section = answer.get(key, {})
        content = section.get("content", "")
        citations = section.get("citations", [])

        print_divider(title)
        print()
        print(content)

        # 【근거 표시】이 섹션이 인용한 조문·판례
        if citations:
            print()
            print(f"  📎 인용: {', '.join(citations)}")

    # ────────────────────────────────────────────────────────────────────
    # 【FAQ】리스트로 저장되어 있음
    # ────────────────────────────────────────────────────────────────────
    faqs = answer.get("follow_up_questions", [])
    if faqs:
        print_divider("7️⃣  자주 묻는 질문")
        print()
        for i, faq in enumerate(faqs, 1):
            print(f"  [{i}]")
            # FAQ는 "Q: ...\nA: ..." 형태
            for line in faq.split("\n"):
                print(f"  {line}")
            print()

    print_divider()


# ════════════════════════════════════════════════════════════════════════════════
# 【실행】질문 하나 처리
# ════════════════════════════════════════════════════════════════════════════════

async def ask(graph, retriever, question: str):

    print_divider("❓ 질문", "━")
    print(f"\n  {question}\n")

    # ────────────────────────────────────────────────────────────────────
    # 【1】검색
    # ────────────────────────────────────────────────────────────────────
    print("  🔍 조문·판례 검색 중...")
    raw_chunks = retriever.search(question)
    search_results = convert_search_results(raw_chunks)

    n_statutes = len(search_results["statutes"])
    n_precedents = len(search_results["precedents"])
    print(f"     → 조문 {n_statutes}개, 판례 {n_precedents}개")

    # ────────────────────────────────────────────────────────────────────
    # 【2】그래프 실행 (GPT 호출)
    # ────────────────────────────────────────────────────────────────────
    print("  🤖 답변 생성 중... (30~45초 소요)")

    start = time.time()

    result = await graph.ainvoke({
        "question": question,
        "search_results": search_results,
        "chat_history": None,
        "user_id": None,
    })

    elapsed = time.time() - start

    # ────────────────────────────────────────────────────────────────────
    # 【3】출력
    # ────────────────────────────────────────────────────────────────────
    answer = result.get("answer")

    if not answer:
        print()
        print(f"  ❌ 답변 생성 실패")
        print(f"     error: {result.get('error')}")
        return

    print_answer(answer, elapsed)


# ════════════════════════════════════════════════════════════════════════════════
# 【대화형 모드】
# ════════════════════════════════════════════════════════════════════════════════

async def chat_mode(graph, retriever):

    print_divider("💬 대화형 모드")
    print()
    print("  질문을 입력하세요. 빈 줄을 입력하면 종료됩니다.")
    print("  ⚠️ 질문 1개당 GPT 8회 호출 (약 30~45초, 비용 발생)")
    print()

    while True:
        try:
            question = input("\n질문> ").strip()

            if not question:
                print("\n종료합니다.")
                break

            await ask(graph, retriever, question)

        except KeyboardInterrupt:
            print("\n\n종료합니다.")
            break


# ════════════════════════════════════════════════════════════════════════════════
# 【메인】
# ════════════════════════════════════════════════════════════════════════════════

async def main():
    print_divider("🏠 C파트 답변 생성 - 콘솔 확인")

    # 【준비】그래프 + Retriever
    print("\n  준비 중...")
    graph = get_c_part_graph()
    retriever = CPartRetriever()
    print("  ✅ 준비 완료\n")

    # ────────────────────────────────────────────────────────────────────
    # 【모드 판단】
    # ────────────────────────────────────────────────────────────────────
    args = sys.argv[1:]


    if args and args[0] == "--chat":
        await chat_mode(graph, retriever)
        return

    if args:
        question = " ".join(args)
        await ask(graph, retriever, question)
        return

    default_question = "보증금 5천만원을 못 받았는데 소송하면 비용이 얼마나 드나요?"
    await ask(graph, retriever, default_question)


if __name__ == "__main__":
    asyncio.run(main())