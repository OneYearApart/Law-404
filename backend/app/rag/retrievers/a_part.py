"""
A파트 검색 전략 (스텁).
"""
from app.rag.retrievers.base import BaseRetriever


class APartRetriever(BaseRetriever):
    def __init__(self):
        super().__init__(table_name="a_part_embeddings")
