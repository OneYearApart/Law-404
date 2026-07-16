"""검증·중복 확인·안전 저장을 하나로 묶은 공통 문서 업로드 서비스."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from app.documents.models import DocumentType, UploadedDocument
from app.documents.storage import FileDocumentRepository
from app.documents.validation import (
    DEFAULT_MAX_UPLOAD_BYTES,
    read_stream_limited,
    validate_upload_bytes,
)


class DocumentUploadService:
    def __init__(
        self,
        *,
        repository: FileDocumentRepository | None = None,
        storage_root: Path | str | None = None,
        max_size_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    ) -> None:
        if repository is not None and storage_root is not None:
            raise ValueError(
                "repository와 storage_root를 동시에 지정할 수 없습니다."
            )
        if max_size_bytes <= 0:
            raise ValueError("max_size_bytes는 1 이상이어야 합니다.")

        self.repository = repository or FileDocumentRepository(storage_root)
        self.max_size_bytes = max_size_bytes

    @staticmethod
    def _normalize_document_type(
        document_type: DocumentType | str,
    ) -> DocumentType:
        if isinstance(document_type, DocumentType):
            return document_type
        return DocumentType(document_type)

    def upload_bytes(
        self,
        *,
        conversation_id: str,
        document_type: DocumentType | str,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> UploadedDocument:
        normalized_type = self._normalize_document_type(document_type)
        validated = validate_upload_bytes(
            filename=filename,
            content_type=content_type,
            data=data,
            max_size_bytes=self.max_size_bytes,
        )
        return self.repository.save(
            conversation_id=conversation_id,
            document_type=normalized_type,
            upload=validated,
        )

    def upload_stream(
        self,
        *,
        conversation_id: str,
        document_type: DocumentType | str,
        filename: str,
        content_type: str | None,
        stream: BinaryIO,
    ) -> UploadedDocument:
        data = read_stream_limited(
            stream,
            max_size_bytes=self.max_size_bytes,
        )
        return self.upload_bytes(
            conversation_id=conversation_id,
            document_type=document_type,
            filename=filename,
            content_type=content_type,
            data=data,
        )

    def list_documents(self, conversation_id: str) -> list[UploadedDocument]:
        return self.repository.list_documents(conversation_id)

    def read_bytes(
        self,
        conversation_id: str,
        document_id: str,
    ) -> bytes:
        return self.repository.read_bytes(conversation_id, document_id)

    def delete_conversation(
        self,
        conversation_id: str,
    ) -> list[UploadedDocument]:
        return self.repository.delete_conversation(conversation_id)

    def delete(
        self,
        conversation_id: str,
        document_id: str,
    ) -> UploadedDocument:
        return self.repository.delete(conversation_id, document_id)
