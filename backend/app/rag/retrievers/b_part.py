"""
B파트 검색 전략 (스텁).
"""
from app.rag.retrievers.base import BaseRetriever


class BPartRetriever(BaseRetriever):
    def __init__(self):
        super().__init__(table_name="b_part_embeddings")
