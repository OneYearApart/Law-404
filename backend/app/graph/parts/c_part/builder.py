from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.graph.parts.c_part.graph import build_c_part_graph


def get_c_part_graph():
    """
    C파트 그래프 인스턴스 반환 (싱글톤 패턴)

    """
    # LLM 생성
    llm = ChatOpenAI(
        model=settings.OPENAI_MODEL,
        temperature=settings.OPENAI_TEMPERATURE,
        api_key=settings.OPENAI_API_KEY,
        # 【재시도】Connection error 자동 복구
        max_retries=3,
        # 【타임아웃】응답이 60초 넘으면 포기
        # → 무한 대기로 테스트가 멈추는 걸 방지
        timeout=60,
    )

    # 그래프 빌드
    return build_c_part_graph(llm)


# 싱글톤
_graph_instance = None


def get_c_part_graph_singleton():
    """싱글톤 인스턴스 반환"""
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = get_c_part_graph()
    return _graph_instance
