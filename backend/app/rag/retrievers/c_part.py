"""
C파트 검색 전략 (스텁).
"""
from app.rag.retrievers.base import BaseRetriever


class CPartRetriever(BaseRetriever):
    def __init__(self):
        super().__init__(table_name="c_part_embeddings")
