"""
D파트 검색 전략.

일반 유사도 검색이 아니라, victim_check의 슬롯매핑 결과를 기준으로
조문 + 관련 판례 + 사례집 케이스를 참조조문/주제태그로 링크해서 함께 가져옵니다.
(원문→해설→상황적용 응답 구조 지원 — 기획서 4.3 참고)
"""
from app.rag.retrievers.base import BaseRetriever


class DPartRetriever(BaseRetriever):
    def __init__(self):
        super().__init__(table_name="d_part_embeddings")

    async def search_by_requirement(self, slot_result: dict):
        statute_chunks = await self.search(query="")  # TODO: 요건 슬롯 기준 조문 검색
        case_law = await self._link_related(statute_chunks, source="판례")
        cases = await self._link_related(statute_chunks, source="사례집")
        return {"statute": statute_chunks, "case_law": case_law, "cases": cases}

    async def _link_related(self, chunks, source: str):
        raise NotImplementedError
