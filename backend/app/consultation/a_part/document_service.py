"""공통 문서 업로드와 OCR 결과를 A파트 ConversationState에 연결한다."""

from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO

from app.consultation.a_part.models import ConversationState
from app.consultation.a_part.service import (
    APartConversationService,
    DEFAULT_CONVERSATION_SERVICE,
)
from app.documents.analysis import (
    ANALYSIS_VERSION,
    ConversationDocumentAnalysisResponse,
    DocumentAnalysisService,
)
from app.documents.analysis.state_mapper import (
    apply_document_analysis_to_state,
    build_document_slot_updates,
)
from app.documents.extraction_models import DocumentExtractionResponse
from app.documents.extraction_service import DocumentExtractionService
from app.documents.models import (
    DocumentType,
    DocumentUploadResult,
    UploadedDocument,
)
from app.documents.service import DocumentUploadService


class APartDocumentUploadService:
    def __init__(
        self,
        *,
        upload_service: DocumentUploadService | None = None,
        extraction_service: DocumentExtractionService | None = None,
        analysis_service: DocumentAnalysisService | None = None,
        conversation_service: APartConversationService | None = None,
        storage_root: Path | str | None = None,
        max_size_bytes: int | None = None,
        database_repository: Any | None = None,
    ) -> None:
        if upload_service is not None and (
            storage_root is not None or max_size_bytes is not None
        ):
            raise ValueError(
                "upload_service를 지정하면 storage_root와 max_size_bytes를 "
                "함께 지정할 수 없습니다."
            )

        if upload_service is None:
            options = {}
            if storage_root is not None:
                options["storage_root"] = storage_root
            if max_size_bytes is not None:
                options["max_size_bytes"] = max_size_bytes
            upload_service = DocumentUploadService(**options)

        self.upload_service = upload_service
        self.extraction_service = extraction_service or DocumentExtractionService(
            repository=upload_service.repository
        )
        self.analysis_service = analysis_service or DocumentAnalysisService(
            repository=upload_service.repository
        )
        self.conversation_service = (
            conversation_service or DEFAULT_CONVERSATION_SERVICE
        )
        self.database_repository = database_repository

    def _persist_document(
        self,
        *,
        document: UploadedDocument,
        state: ConversationState,
    ) -> None:
        if self.database_repository is None:
            return
        same_type = [
            item
            for item in state.documents
            if item.document_type == document.document_type
        ]
        page_index = next(
            (
                index
                for index, item in enumerate(same_type, start=1)
                if item.document_id == document.document_id
            ),
            len(same_type) or 1,
        )
        data = self.upload_service.read_bytes(
            document.conversation_id,
            document.document_id,
        )
        self.database_repository.upsert_document(
            document_id=document.document_id,
            conversation_id=document.conversation_id,
            source_type="pdf",
            document_type=document.document_type.value,
            page_index=page_index,
            original_filename=document.original_filename,
            content_type=document.content_type,
            data=data,
            sha256=document.sha256,
        )

    def _persist_state(self, state: ConversationState) -> None:
        if self.database_repository is None:
            return
        self.database_repository.upsert_state(
            conversation_id=state.conversation_id,
            state=state,
        )

    def _attach(
        self,
        *,
        conversation_id: str,
        document: UploadedDocument,
    ) -> ConversationState:
        try:
            return self.conversation_service.attach_document(
                conversation_id,
                document,
            )
        except Exception:
            if not document.is_duplicate:
                try:
                    self.upload_service.delete(
                        conversation_id,
                        document.document_id,
                    )
                except Exception:
                    pass
            raise

    def upload_bytes(
        self,
        *,
        conversation_id: str,
        document_type: DocumentType | str,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> DocumentUploadResult:
        self.conversation_service.get_state(conversation_id)

        document = self.upload_service.upload_bytes(
            conversation_id=conversation_id,
            document_type=document_type,
            filename=filename,
            content_type=content_type,
            data=data,
        )
        state = self._attach(
            conversation_id=conversation_id,
            document=document,
        )
        self._persist_document(document=document, state=state)
        self._persist_state(state)

        warnings: list[str] = []
        if document.is_duplicate:
            warnings.append(
                "같은 내용의 파일이 이미 이 상담에 있어 기존 문서를 재사용했습니다."
            )

        return DocumentUploadResult(
            document=document,
            conversation_document_count=len(state.documents),
            warnings=warnings,
            state=state,
        )

    def upload_stream(
        self,
        *,
        conversation_id: str,
        document_type: DocumentType | str,
        filename: str,
        content_type: str | None,
        stream: BinaryIO,
    ) -> DocumentUploadResult:
        self.conversation_service.get_state(conversation_id)

        document = self.upload_service.upload_stream(
            conversation_id=conversation_id,
            document_type=document_type,
            filename=filename,
            content_type=content_type,
            stream=stream,
        )
        state = self._attach(
            conversation_id=conversation_id,
            document=document,
        )
        self._persist_document(document=document, state=state)
        self._persist_state(state)

        warnings: list[str] = []
        if document.is_duplicate:
            warnings.append(
                "같은 내용의 파일이 이미 이 상담에 있어 기존 문서를 재사용했습니다."
            )

        return DocumentUploadResult(
            document=document,
            conversation_document_count=len(state.documents),
            warnings=warnings,
            state=state,
        )

    def extract_document(
        self,
        *,
        conversation_id: str,
        document_id: str,
        force: bool = False,
    ) -> DocumentExtractionResponse:
        state = self.conversation_service.get_state(conversation_id)
        if not any(
            item.document_id == document_id
            for item in state.documents
        ):
            raise ValueError(
                f"현재 상담에 연결되지 않은 document_id입니다: {document_id}"
            )

        extraction = self.extraction_service.extract(
            conversation_id=conversation_id,
            document_id=document_id,
            force=force,
        )
        updated_document = self.upload_service.repository.get(
            conversation_id,
            document_id,
        )
        updated_state = self.conversation_service.update_document(
            conversation_id,
            updated_document,
        )
        if self.database_repository is not None:
            self.database_repository.upsert_extraction(extraction)
            self._persist_state(updated_state)
        return DocumentExtractionResponse(
            document=updated_document,
            extraction=extraction,
            state=updated_state,
        )


    def analyze_documents(
        self,
        *,
        conversation_id: str,
        document_ids: list[str] | None = None,
        force: bool = False,
    ) -> ConversationDocumentAnalysisResponse:
        state = self.conversation_service.get_state(conversation_id)
        connected_ids = {item.document_id for item in state.documents}
        requested_ids = set(document_ids or [])
        if requested_ids and not requested_ids.issubset(connected_ids):
            missing = sorted(requested_ids - connected_ids)
            raise ValueError(
                "현재 상담에 연결되지 않은 document_id입니다: "
                + ", ".join(missing)
            )

        response = self.analysis_service.analyze_conversation_documents(
            conversation_id=conversation_id,
            document_ids=document_ids,
            force=force,
        )

        for analysis in [
            *response.lease_analyses,
            *response.registry_analyses,
        ]:
            source_ids = analysis.source_document_ids or [analysis.document_id]
            for source_document_id in source_ids:
                updated_document = self.upload_service.repository.get(
                    conversation_id,
                    source_document_id,
                )
                state.update_document(updated_document)

        comparison = response.comparison
        updates = build_document_slot_updates(
            lease=(response.lease_analyses[-1] if response.lease_analyses else None),
            registry=(response.registry_analyses[-1] if response.registry_analyses else None),
            comparison=comparison,
        )
        mapping = apply_document_analysis_to_state(
            state,
            updates=updates,
            triggered_issue_ids=(comparison.triggered_issue_ids if comparison else []),
            comparison_result_path=(comparison.comparison_result_path if comparison else None),
            analysis_version=ANALYSIS_VERSION,
        )
        stored_state = self.conversation_service.store.save(state)
        if self.database_repository is not None:
            for analysis in response.lease_analyses:
                self.database_repository.upsert_analysis(
                    conversation_id=conversation_id,
                    source_type="pdf",
                    document_type="lease_contract",
                    analysis_version=ANALYSIS_VERSION,
                    source_document_ids=(
                        analysis.source_document_ids or [analysis.document_id]
                    ),
                    result=analysis,
                )
            for analysis in response.registry_analyses:
                self.database_repository.upsert_analysis(
                    conversation_id=conversation_id,
                    source_type="pdf",
                    document_type="registry",
                    analysis_version=ANALYSIS_VERSION,
                    source_document_ids=(
                        analysis.source_document_ids or [analysis.document_id]
                    ),
                    result=analysis,
                )
            if response.comparison is not None:
                self.database_repository.upsert_comparison(
                    conversation_id=conversation_id,
                    source_type="pdf",
                    analysis_version=ANALYSIS_VERSION,
                    result=response.comparison,
                )
            self._persist_state(stored_state)
        return response.model_copy(
            update={
                "state_mapping": mapping,
                "state": stored_state,
            }
        )

    def analyze_document(
        self,
        *,
        conversation_id: str,
        document_id: str,
        force: bool = False,
    ) -> ConversationDocumentAnalysisResponse:
        return self.analyze_documents(
            conversation_id=conversation_id,
            document_ids=[document_id],
            force=force,
        )

    def list_documents(self, conversation_id: str):
        state = self.conversation_service.get_state(conversation_id)
        return [item.model_copy(deep=True) for item in state.documents]

    def delete_conversation_artifacts(
        self,
        *,
        conversation_id: str,
    ) -> dict[str, Any]:
        """상담에 연결된 파일과 문서 처리 DB 결과를 모두 정리한다."""

        state = self.conversation_service.get_state(conversation_id)
        removed_files = self.upload_service.delete_conversation(conversation_id)

        database_cleanup = {
            "documents": 0,
            "extractions": 0,
            "analyses": 0,
            "comparisons": 0,
        }
        if self.database_repository is not None:
            database_cleanup = (
                self.database_repository.delete_conversation_artifacts(
                    conversation_id=conversation_id
                )
            )

        return {
            "conversation_id": conversation_id,
            "state_document_count": len(state.documents),
            "deleted_file_count": len(removed_files),
            "database_cleanup": database_cleanup,
        }

    def delete_document(
        self,
        *,
        conversation_id: str,
        document_id: str,
    ) -> UploadedDocument:
        state = self.conversation_service.get_state(conversation_id)
        if not any(item.document_id == document_id for item in state.documents):
            raise ValueError(
                f"현재 상담에 연결되지 않은 document_id입니다: {document_id}"
            )

        removed = self.upload_service.delete(conversation_id, document_id)
        state.remove_document(document_id)
        stored_state = self.conversation_service.store.save(state)
        if self.database_repository is not None:
            self.database_repository.delete_document(
                conversation_id=conversation_id,
                document_id=document_id,
            )
            self._persist_state(stored_state)
        return removed


_DEFAULT_A_PART_DOCUMENT_UPLOAD_SERVICE: APartDocumentUploadService | None = None


def get_default_a_part_document_upload_service() -> APartDocumentUploadService:
    global _DEFAULT_A_PART_DOCUMENT_UPLOAD_SERVICE
    if _DEFAULT_A_PART_DOCUMENT_UPLOAD_SERVICE is None:
        _DEFAULT_A_PART_DOCUMENT_UPLOAD_SERVICE = APartDocumentUploadService()
    return _DEFAULT_A_PART_DOCUMENT_UPLOAD_SERVICE


def upload_document_bytes(**kwargs) -> DocumentUploadResult:
    return get_default_a_part_document_upload_service().upload_bytes(**kwargs)


def upload_document_stream(**kwargs) -> DocumentUploadResult:
    return get_default_a_part_document_upload_service().upload_stream(**kwargs)


def extract_document_text(**kwargs) -> DocumentExtractionResponse:
    return get_default_a_part_document_upload_service().extract_document(**kwargs)


def analyze_conversation_documents(**kwargs) -> ConversationDocumentAnalysisResponse:
    return get_default_a_part_document_upload_service().analyze_documents(**kwargs)
