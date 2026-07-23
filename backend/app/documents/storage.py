"""검증이 끝난 업로드 파일과 메타데이터를 안전한 경로에 저장한다."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from threading import RLock
from uuid import uuid4

from app.documents.models import DocumentType, UploadedDocument
from app.documents.validation import ValidatedUpload

SAFE_CONVERSATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class DocumentStorageError(RuntimeError):
    """문서 파일이나 메타데이터 저장에 실패했을 때 발생한다."""


class DocumentNotFoundError(DocumentStorageError):
    pass


class DuplicateDocumentTypeConflictError(DocumentStorageError):
    """같은 파일이 다른 문서 유형으로 이미 등록돼 있을 때 발생한다."""


class FileDocumentRepository:
    """문서 원본과 대화별 메타데이터 인덱스를 파일시스템에 보관한다."""

    def __init__(self, root: Path | str | None = None) -> None:
        default_root = (
            Path(__file__).resolve().parents[2] / "storage" / "a_part" / "uploads"
        )
        self.root = Path(root or default_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    @staticmethod
    def validate_conversation_id(conversation_id: str) -> str:
        normalized = conversation_id.strip()
        if not SAFE_CONVERSATION_ID.fullmatch(normalized):
            raise DocumentStorageError(
                "conversation_id는 영문, 숫자, 하이픈, 밑줄만 사용할 수 있습니다."
            )
        return normalized

    def _conversation_dir(self, conversation_id: str) -> Path:
        normalized = self.validate_conversation_id(conversation_id)
        directory = (self.root / normalized).resolve()
        if self.root not in directory.parents:
            raise DocumentStorageError("안전하지 않은 문서 저장 경로입니다.")
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _index_path(self, conversation_id: str) -> Path:
        return self._conversation_dir(conversation_id) / ".documents.json"

    def _load_index(self, conversation_id: str) -> list[UploadedDocument]:
        path = self._index_path(conversation_id)
        if not path.exists():
            return []

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise TypeError("문서 인덱스가 list가 아닙니다.")
            return [UploadedDocument.model_validate(item) for item in raw]
        except Exception as error:
            raise DocumentStorageError(
                f"문서 메타데이터 인덱스를 읽지 못했습니다: {path}"
            ) from error

    @staticmethod
    def _atomic_write_bytes(path: Path, data: bytes) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.part")
        try:
            with temporary.open("xb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _atomic_write_json(path: Path, documents: list[UploadedDocument]) -> None:
        payload = [item.model_dump(mode="json") for item in documents]
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.part")
        try:
            with temporary.open("x", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.flush()
                os.fsync(file.fileno())
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def save(
        self,
        *,
        conversation_id: str,
        document_type: DocumentType,
        upload: ValidatedUpload,
    ) -> UploadedDocument:
        normalized_conversation_id = self.validate_conversation_id(conversation_id)

        with self._lock:
            existing_documents = self._load_index(normalized_conversation_id)
            duplicate = next(
                (item for item in existing_documents if item.sha256 == upload.sha256),
                None,
            )

            if duplicate is not None:
                if duplicate.document_type != document_type:
                    raise DuplicateDocumentTypeConflictError(
                        "같은 파일이 이미 다른 문서 유형으로 등록돼 있습니다: "
                        f"{duplicate.document_type.value}"
                    )
                return duplicate.model_copy(
                    update={
                        "is_duplicate": True,
                        "duplicate_of": duplicate.document_id,
                    }
                )

            document_id = str(uuid4())
            stored_filename = f"{document_id}{upload.canonical_extension}"
            relative_path = (
                Path(normalized_conversation_id) / stored_filename
            ).as_posix()
            target = self.root / relative_path

            metadata = UploadedDocument(
                document_id=document_id,
                conversation_id=normalized_conversation_id,
                document_type=document_type,
                original_filename=upload.original_filename,
                safe_filename=upload.safe_filename,
                stored_filename=stored_filename,
                stored_path=relative_path,
                detected_format=upload.detected_format,
                content_type=upload.canonical_content_type,
                declared_content_type=upload.declared_content_type,
                size_bytes=upload.size_bytes,
                sha256=upload.sha256,
            )

            try:
                self._atomic_write_bytes(target, upload.data)
                updated_documents = [*existing_documents, metadata]
                self._atomic_write_json(
                    self._index_path(normalized_conversation_id),
                    updated_documents,
                )
            except Exception as error:
                target.unlink(missing_ok=True)
                if isinstance(error, DocumentStorageError):
                    raise
                raise DocumentStorageError(
                    "문서 원본 또는 메타데이터 저장에 실패했습니다."
                ) from error

            return metadata

    def list_documents(self, conversation_id: str) -> list[UploadedDocument]:
        with self._lock:
            return [
                item.model_copy(deep=True) for item in self._load_index(conversation_id)
            ]

    def get(
        self,
        conversation_id: str,
        document_id: str,
    ) -> UploadedDocument:
        documents = self.list_documents(conversation_id)
        try:
            return next(item for item in documents if item.document_id == document_id)
        except StopIteration as error:
            raise DocumentNotFoundError(
                f"문서를 찾을 수 없습니다: {document_id}"
            ) from error

    def resolve_relative_path(self, relative_path: str) -> Path:
        normalized = relative_path.replace("\\", "/").strip()
        if (
            not normalized
            or normalized.startswith("/")
            or ".." in normalized.split("/")
        ):
            raise DocumentStorageError("안전하지 않은 문서 상대 경로입니다.")
        path = (self.root / normalized).resolve()
        if self.root not in path.parents:
            raise DocumentStorageError("안전하지 않은 문서 경로입니다.")
        return path

    def resolve_path(self, document: UploadedDocument) -> Path:
        return self.resolve_relative_path(document.stored_path)

    def update_document(self, document: UploadedDocument) -> UploadedDocument:
        normalized_conversation_id = self.validate_conversation_id(
            document.conversation_id
        )
        with self._lock:
            documents = self._load_index(normalized_conversation_id)
            found = False
            updated: list[UploadedDocument] = []
            for item in documents:
                if item.document_id == document.document_id:
                    updated.append(document.model_copy(deep=True))
                    found = True
                else:
                    updated.append(item)
            if not found:
                raise DocumentNotFoundError(
                    f"문서를 찾을 수 없습니다: {document.document_id}"
                )
            self._atomic_write_json(
                self._index_path(normalized_conversation_id),
                updated,
            )
            return document.model_copy(deep=True)

    def read_bytes(
        self,
        conversation_id: str,
        document_id: str,
    ) -> bytes:
        document = self.get(conversation_id, document_id)
        path = self.resolve_path(document)
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise DocumentNotFoundError(
                f"저장된 원본 파일을 찾을 수 없습니다: {document_id}"
            ) from error

    def delete_conversation(
        self,
        conversation_id: str,
    ) -> list[UploadedDocument]:
        """상담에 연결된 원본·파생 파일과 메타데이터 디렉터리를 삭제한다."""

        normalized = self.validate_conversation_id(conversation_id)
        directory = (self.root / normalized).resolve()
        if self.root not in directory.parents:
            raise DocumentStorageError("안전하지 않은 문서 저장 경로입니다.")

        with self._lock:
            if not directory.exists():
                return []

            documents = self._load_index(normalized)
            try:
                shutil.rmtree(directory)
            except OSError as error:
                raise DocumentStorageError(
                    "상담에 연결된 문서 파일을 삭제하지 못했습니다."
                ) from error

            return [item.model_copy(deep=True) for item in documents]

    def delete(
        self,
        conversation_id: str,
        document_id: str,
    ) -> UploadedDocument:
        with self._lock:
            documents = self._load_index(conversation_id)
            target = next(
                (item for item in documents if item.document_id == document_id),
                None,
            )
            if target is None:
                raise DocumentNotFoundError(f"문서를 찾을 수 없습니다: {document_id}")

            remaining = [item for item in documents if item.document_id != document_id]
            self.resolve_path(target).unlink(missing_ok=True)
            for extra_path in (
                target.extraction_result_path,
                target.extracted_text_path,
                target.analysis_result_path,
            ):
                if extra_path:
                    self.resolve_relative_path(extra_path).unlink(missing_ok=True)
            comparison_path = (
                f"{target.conversation_id}/"
                f"{target.conversation_id}.document_comparison.json"
            )
            self.resolve_relative_path(comparison_path).unlink(missing_ok=True)
            self._atomic_write_json(
                self._index_path(conversation_id),
                remaining,
            )
            return target
