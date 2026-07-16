"""
등기부등본 등 문서 인식 에이전트 (파트 공통).
로컬 OCR 모델 도입 후보 지점 — local_model/models/d_part/ 참고 (한국 공문서 특화 검토 중).
"""


async def extract_document(file_bytes: bytes) -> dict:
    raise NotImplementedError
