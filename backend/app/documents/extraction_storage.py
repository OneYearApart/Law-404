"""OCR 결과 JSON과 통합 TXT를 업로드 원본 옆에 안전하게 저장한다."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.documents.extraction_models import DocumentExtractionResult
from app.documents.models import UploadedDocument
from app.documents.storage import DocumentStorageError, FileDocumentRepository


class ExtractionResultNotFoundError(DocumentStorageError):
    pass


class DocumentExtractionStorage:
    def __init__(self, repository: FileDocumentRepository) -> None:
        self.repository = repository
        self._lock = RLock()

    @staticmethod
    def _atomic_write_text(path: Path, text: str) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.part")
        try:
            with temporary.open("x", encoding="utf-8") as file:
                file.write(text)
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.part")
        try:
            with temporary.open("x", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def relative_paths(self, document: UploadedDocument) -> tuple[str, str]:
        conversation_id = self.repository.validate_conversation_id(
            document.conversation_id
        )
        base = Path(conversation_id) / document.document_id
        return (
            f"{base.as_posix()}.extraction.json",
            f"{base.as_posix()}.txt",
        )

    def save(
        self,
        document: UploadedDocument,
        result: DocumentExtractionResult,
    ) -> DocumentExtractionResult:
        if result.document_id != document.document_id:
            raise DocumentStorageError(
                "추출 결과 document_id가 업로드 문서와 다릅니다."
            )
        if result.conversation_id != document.conversation_id:
            raise DocumentStorageError(
                "추출 결과 conversation_id가 업로드 문서와 다릅니다."
            )

        result_path, text_path = self.relative_paths(document)
        result_with_paths = result.model_copy(
            update={
                "extraction_result_path": result_path,
                "extracted_text_path": text_path,
            }
        )
        absolute_result_path = self.repository.resolve_relative_path(result_path)
        absolute_text_path = self.repository.resolve_relative_path(text_path)
        absolute_result_path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            try:
                self._atomic_write_text(
                    absolute_text_path,
                    result_with_paths.combined_text,
                )
                self._atomic_write_json(
                    absolute_result_path,
                    result_with_paths.model_dump(mode="json"),
                )
            except Exception as error:
                absolute_text_path.unlink(missing_ok=True)
                absolute_result_path.unlink(missing_ok=True)
                if isinstance(error, DocumentStorageError):
                    raise
                raise DocumentStorageError(
                    "문서 텍스트 추출 결과 파일 저장에 실패했습니다."
                ) from error

        return result_with_paths

    def load(
        self,
        document: UploadedDocument,
    ) -> DocumentExtractionResult:
        result_path, _ = self.relative_paths(document)
        absolute = self.repository.resolve_relative_path(result_path)
        if not absolute.exists():
            raise ExtractionResultNotFoundError(
                f"추출 결과를 찾을 수 없습니다: {document.document_id}"
            )
        try:
            payload = json.loads(absolute.read_text(encoding="utf-8"))
            return DocumentExtractionResult.model_validate(payload)
        except Exception as error:
            raise DocumentStorageError(
                f"추출 결과 JSON을 읽지 못했습니다: {absolute}"
            ) from error

    def current_result(
        self,
        document: UploadedDocument,
        *,
        extraction_version: str,
    ) -> DocumentExtractionResult | None:
        try:
            result = self.load(document)
        except ExtractionResultNotFoundError:
            return None

        if result.source_sha256 != document.sha256:
            return None
        if result.extraction_version != extraction_version:
            return None
        if not result.extracted_text_path:
            return None
        text_path = self.repository.resolve_relative_path(
            result.extracted_text_path
        )
        if not text_path.exists():
            return None
        return result.model_copy(update={"reused": True})

    def delete(self, document: UploadedDocument) -> None:
        result_path, text_path = self.relative_paths(document)
        self.repository.resolve_relative_path(result_path).unlink(missing_ok=True)
        self.repository.resolve_relative_path(text_path).unlink(missing_ok=True)
