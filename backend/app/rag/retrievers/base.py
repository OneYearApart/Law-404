"""
pgvector 검색 공통 인터페이스.
파트별 retriever(a_part.py ~ d_part.py)가 이 클래스를 상속해서 사용합니다.
"""
from app.rag.embeddings.base import embed


class BaseRetriever:
    def __init__(self, table_name: str):
        self.table_name = table_name

    async def search(self, query: str, top_k: int = 5):
        query_vector = await embed(query)
        raise NotImplementedError
