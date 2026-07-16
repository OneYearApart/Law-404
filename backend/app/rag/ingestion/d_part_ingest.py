"""
D파트 데이터 적재 스크립트.

소스: docs/d_part/raw/
  - 전세사기피해자법_전문.pdf        (조 단위 청킹)
  - HUG_2025_전세피해지원_사례집.pdf (케이스 Q+A 단위 청킹)
  - HUG_전세피해_예방_종합안내.pdf   (섹션 기준 청킹)
  - 판례(law.go.kr API 별도 수집)     (판결요지 우선, 필요시 전문 분리)

적재 대상: d_part_embeddings 테이블 (db/schema/d_part_tables.sql)
"""
from app.rag.embeddings.base import embed


async def ingest():
    raise NotImplementedError


if __name__ == "__main__":
    import asyncio
    asyncio.run(ingest())
