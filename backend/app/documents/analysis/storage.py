"""문서 필드 분석과 계약서·등기부 비교 결과를 JSON으로 저장한다."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock
from uuid import uuid4

from backend.app.documents.analysis.models import (
    ANALYSIS_VERSION,
    DocumentComparisonResult,
    LeaseAnalysisResult,
    RegistryAnalysisResult,
)
from backend.app.documents.models import DocumentType, UploadedDocument
from backend.app.documents.storage import DocumentStorageError, FileDocumentRepository


class AnalysisResultNotFoundError(DocumentStorageError):
    pass


class DocumentAnalysisStorage:
    def __init__(self, repository: FileDocumentRepository) -> None:
        self.repository = repository
        self._lock = RLock()

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

    def document_relative_path(self, document: UploadedDocument) -> str:
        conversation_id = self.repository.validate_conversation_id(
            document.conversation_id
        )
        suffix = {
            DocumentType.LEASE_CONTRACT: "lease_analysis.json",
            DocumentType.REGISTRY: "registry_analysis.json",
        }.get(document.document_type)
        if suffix is None:
            raise DocumentStorageError(
                "현재 분석 저장은 lease_contract와 registry 문서만 지원합니다."
            )
        return f"{conversation_id}/{document.document_id}.{suffix}"

    def comparison_relative_path(self, conversation_id: str) -> str:
        normalized = self.repository.validate_conversation_id(conversation_id)
        return f"{normalized}/{normalized}.document_comparison.json"

    def save_lease(
        self,
        document: UploadedDocument,
        result: LeaseAnalysisResult,
    ) -> LeaseAnalysisResult:
        if result.document_id != document.document_id:
            raise DocumentStorageError("계약서 분석 document_id가 원본과 다릅니다.")
        relative_path = self.document_relative_path(document)
        stored = result.model_copy(update={"analysis_result_path": relative_path})
        absolute = self.repository.resolve_relative_path(relative_path)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._atomic_write_json(absolute, stored.model_dump(mode="json"))
        return stored

    def save_registry(
        self,
        document: UploadedDocument,
        result: RegistryAnalysisResult,
    ) -> RegistryAnalysisResult:
        if result.document_id != document.document_id:
            raise DocumentStorageError("등기부 분석 document_id가 원본과 다릅니다.")
        relative_path = self.document_relative_path(document)
        stored = result.model_copy(update={"analysis_result_path": relative_path})
        absolute = self.repository.resolve_relative_path(relative_path)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._atomic_write_json(absolute, stored.model_dump(mode="json"))
        return stored

    def save_comparison(
        self,
        result: DocumentComparisonResult,
    ) -> DocumentComparisonResult:
        relative_path = self.comparison_relative_path(result.conversation_id)
        stored = result.model_copy(update={"comparison_result_path": relative_path})
        absolute = self.repository.resolve_relative_path(relative_path)
        absolute.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._atomic_write_json(absolute, stored.model_dump(mode="json"))
        return stored

    def load_lease(self, document: UploadedDocument) -> LeaseAnalysisResult:
        absolute = self.repository.resolve_relative_path(
            self.document_relative_path(document)
        )
        if not absolute.exists():
            raise AnalysisResultNotFoundError(
                f"계약서 분석 결과를 찾을 수 없습니다: {document.document_id}"
            )
        try:
            return LeaseAnalysisResult.model_validate_json(
                absolute.read_text(encoding="utf-8")
            )
        except Exception as error:
            raise DocumentStorageError(
                f"계약서 분석 JSON을 읽지 못했습니다: {absolute}"
            ) from error

    def load_registry(self, document: UploadedDocument) -> RegistryAnalysisResult:
        absolute = self.repository.resolve_relative_path(
            self.document_relative_path(document)
        )
        if not absolute.exists():
            raise AnalysisResultNotFoundError(
                f"등기부 분석 결과를 찾을 수 없습니다: {document.document_id}"
            )
        try:
            return RegistryAnalysisResult.model_validate_json(
                absolute.read_text(encoding="utf-8")
            )
        except Exception as error:
            raise DocumentStorageError(
                f"등기부 분석 JSON을 읽지 못했습니다: {absolute}"
            ) from error

    def current_lease(
        self,
        document: UploadedDocument,
        *,
        extraction_version: str,
        analysis_version: str = ANALYSIS_VERSION,
    ) -> LeaseAnalysisResult | None:
        try:
            result = self.load_lease(document)
        except AnalysisResultNotFoundError:
            return None
        if result.source_sha256 != document.sha256:
            return None
        if result.source_extraction_version != extraction_version:
            return None
        if result.analysis_version != analysis_version:
            return None
        return result.model_copy(update={"reused": True})

    def current_registry(
        self,
        document: UploadedDocument,
        *,
        extraction_version: str,
        analysis_version: str = ANALYSIS_VERSION,
    ) -> RegistryAnalysisResult | None:
        try:
            result = self.load_registry(document)
        except AnalysisResultNotFoundError:
            return None
        if result.source_sha256 != document.sha256:
            return None
        if result.source_extraction_version != extraction_version:
            return None
        if result.analysis_version != analysis_version:
            return None
        return result.model_copy(update={"reused": True})
