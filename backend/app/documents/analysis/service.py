"""계약서·등기부 분석, 비교, 결과 저장을 연결하는 서비스."""

from __future__ import annotations

import hashlib
import re

from app.documents.analysis.comparison import compare_documents
from app.documents.analysis.lease_analyzer import analyze_lease_contract
from app.documents.analysis.models import (
    ANALYSIS_VERSION,
    ConversationDocumentAnalysisResponse,
    LeaseAnalysisResult,
    RegistryAnalysisResult,
)
from app.documents.analysis.registry_analyzer import analyze_registry
from app.documents.analysis.storage import DocumentAnalysisStorage
from app.documents.extraction_models import (
    DocumentExtractionResult,
    ExtractionMethod,
    PageExtractionStatus,
)
from app.documents.extraction_storage import DocumentExtractionStorage
from app.documents.models import (
    DocumentAnalysisStatus,
    DocumentProcessingStatus,
    DocumentType,
    UploadedDocument,
    utc_now,
)
from app.documents.storage import FileDocumentRepository


class UnsupportedAnalysisDocumentTypeError(ValueError):
    pass


class ExtractionRequiredError(RuntimeError):
    pass


class DocumentAnalysisService:
    def __init__(
        self,
        *,
        repository: FileDocumentRepository,
        extraction_storage: DocumentExtractionStorage | None = None,
        analysis_storage: DocumentAnalysisStorage | None = None,
        analysis_version: str = ANALYSIS_VERSION,
    ) -> None:
        self.repository = repository
        self.extraction_storage = extraction_storage or DocumentExtractionStorage(
            repository
        )
        self.analysis_storage = analysis_storage or DocumentAnalysisStorage(
            repository
        )
        self.analysis_version = analysis_version

    @staticmethod
    def _ensure_supported(document: UploadedDocument) -> None:
        if document.document_type not in {
            DocumentType.LEASE_CONTRACT,
            DocumentType.REGISTRY,
        }:
            raise UnsupportedAnalysisDocumentTypeError(
                "현재 필드 분석은 lease_contract와 registry 문서를 지원합니다."
            )

    def _load_extraction(
        self,
        document: UploadedDocument,
    ) -> DocumentExtractionResult:
        extraction = self.extraction_storage.load(document)
        if extraction.processing_status == DocumentProcessingStatus.FAILED:
            raise ExtractionRequiredError(
                "문서 텍스트 추출이 실패해 필드 분석을 진행할 수 없습니다."
            )
        if not extraction.combined_text.strip():
            raise ExtractionRequiredError(
                "추출된 문서 텍스트가 비어 있어 필드 분석을 진행할 수 없습니다."
            )
        return extraction

    def _mark_analyzing(self, document: UploadedDocument) -> UploadedDocument:
        updated = document.model_copy(
            update={
                "analysis_status": DocumentAnalysisStatus.ANALYZING,
                "analysis_version": self.analysis_version,
                "analysis_result_path": None,
                "analysis_warnings": [],
                "analysis_error": None,
                "analysis_started_at": utc_now(),
                "analysis_completed_at": None,
            }
        )
        return self.repository.update_document(updated)

    def _mark_completed(
        self,
        document: UploadedDocument,
        *,
        result_path: str | None,
        warnings: list[str],
        partial: bool,
    ) -> UploadedDocument:
        updated = document.model_copy(
            update={
                "analysis_status": (
                    DocumentAnalysisStatus.PARTIAL
                    if partial
                    else DocumentAnalysisStatus.COMPLETED
                ),
                "analysis_version": self.analysis_version,
                "analysis_result_path": result_path,
                "analysis_warnings": warnings,
                "analysis_error": None,
                "analysis_completed_at": utc_now(),
            }
        )
        return self.repository.update_document(updated)

    def _mark_failed(
        self,
        document: UploadedDocument,
        error: Exception,
    ) -> None:
        updated = document.model_copy(
            update={
                "analysis_status": DocumentAnalysisStatus.FAILED,
                "analysis_version": self.analysis_version,
                "analysis_error": f"{error.__class__.__name__}: {error}",
                "analysis_completed_at": utc_now(),
            }
        )
        self.repository.update_document(updated)

    def analyze_document(
        self,
        *,
        conversation_id: str,
        document_id: str,
        force: bool = False,
    ) -> LeaseAnalysisResult | RegistryAnalysisResult:
        document = self.repository.get(conversation_id, document_id)
        self._ensure_supported(document)
        extraction = self._load_extraction(document)

        if not force:
            if document.document_type == DocumentType.LEASE_CONTRACT:
                current = self.analysis_storage.current_lease(
                    document,
                    extraction_version=extraction.extraction_version,
                    analysis_version=self.analysis_version,
                )
            else:
                current = self.analysis_storage.current_registry(
                    document,
                    extraction_version=extraction.extraction_version,
                    analysis_version=self.analysis_version,
                )
            if current is not None:
                self._mark_completed(
                    document,
                    result_path=current.analysis_result_path,
                    warnings=current.warnings,
                    partial=bool(current.errors),
                )
                return current

        analyzing = self._mark_analyzing(document)
        try:
            if analyzing.document_type == DocumentType.LEASE_CONTRACT:
                result = analyze_lease_contract(
                    document=analyzing,
                    extraction=extraction,
                ).model_copy(update={"source_document_ids": [analyzing.document_id]})
                stored = self.analysis_storage.save_lease(analyzing, result)
            else:
                result = analyze_registry(
                    document=analyzing,
                    extraction=extraction,
                ).model_copy(update={"source_document_ids": [analyzing.document_id]})
                stored = self.analysis_storage.save_registry(analyzing, result)

            self._mark_completed(
                analyzing,
                result_path=stored.analysis_result_path,
                warnings=stored.warnings,
                partial=(
                    extraction.processing_status == DocumentProcessingStatus.PARTIAL
                    or bool(stored.errors)
                ),
            )
            return stored
        except Exception as error:
            self._mark_failed(analyzing, error)
            raise

    @staticmethod
    def _natural_document_key(document: UploadedDocument):
        parts = re.split(r"(\d+)", document.original_filename.lower())
        return tuple(int(part) if part.isdigit() else part for part in parts)

    def _merge_group(
        self,
        documents: list[UploadedDocument],
        extractions: list[DocumentExtractionResult],
    ) -> tuple[UploadedDocument, DocumentExtractionResult]:
        ordered = sorted(documents, key=self._natural_document_key)
        extraction_by_id = {item.document_id: item for item in extractions}
        ordered_extractions = [extraction_by_id[item.document_id] for item in ordered]
        digest = hashlib.sha256()
        pages = []
        for extraction in ordered_extractions:
            digest.update(extraction.source_sha256.encode("ascii"))
            for page in extraction.pages:
                pages.append(page.model_copy(update={"page_number": len(pages) + 1}))
        merged_sha = digest.hexdigest()
        successful = sum(page.status == PageExtractionStatus.COMPLETED for page in pages)
        failed = sum(page.status == PageExtractionStatus.FAILED for page in pages)
        direct_count = sum(
            page.status == PageExtractionStatus.COMPLETED
            and page.extraction_method == ExtractionMethod.DIRECT_TEXT
            for page in pages
        )
        ocr_count = sum(
            page.status == PageExtractionStatus.COMPLETED
            and page.extraction_method == ExtractionMethod.OCR
            for page in pages
        )
        methods = {page.extraction_method for page in pages if page.status == PageExtractionStatus.COMPLETED}
        method = (
            next(iter(methods))
            if len(methods) == 1
            else ExtractionMethod.MIXED
            if methods
            else ExtractionMethod.NONE
        )
        ocr_values = [page.ocr_confidence for page in pages if page.ocr_confidence is not None]
        direct_values = [
            page.direct_text_quality_score
            for page in pages
            if page.direct_text_quality_score is not None
        ]
        combined_text = "\n\n".join(
            f"--- 페이지 {page.page_number} ---\n{page.text.strip()}"
            for page in pages
            if page.status == PageExtractionStatus.COMPLETED and page.text.strip()
        ).strip()
        first = ordered[0]
        group_id = f"{first.document_type.value}-group-{merged_sha[:16]}"
        group_document = first.model_copy(
            update={
                "document_id": group_id,
                "original_filename": f"{first.document_type.value}_group",
                "safe_filename": f"{first.document_type.value}_group",
                "stored_filename": f"{group_id}.group",
                "stored_path": f"{first.conversation_id}/{group_id}.group",
                "size_bytes": sum(item.size_bytes for item in ordered),
                "sha256": merged_sha,
                "processing_status": (
                    DocumentProcessingStatus.COMPLETED
                    if failed == 0
                    else DocumentProcessingStatus.PARTIAL
                    if successful
                    else DocumentProcessingStatus.FAILED
                ),
                "page_count": len(pages),
                "successful_page_count": successful,
                "failed_page_count": failed,
                "direct_text_page_count": direct_count,
                "ocr_page_count": ocr_count,
                "text_character_count": len(combined_text),
                "is_duplicate": False,
                "duplicate_of": None,
            }
        )
        first_extraction = ordered_extractions[0]
        merged = DocumentExtractionResult(
            document_id=group_id,
            conversation_id=first.conversation_id,
            source_sha256=merged_sha,
            processing_status=group_document.processing_status,
            extraction_method=method,
            pdf_strategy=first_extraction.pdf_strategy,
            detected_format=first.detected_format.value,
            page_count=len(pages),
            successful_page_count=successful,
            failed_page_count=failed,
            direct_text_page_count=direct_count,
            ocr_page_count=ocr_count,
            text_character_count=len(combined_text),
            average_ocr_confidence=(sum(ocr_values) / len(ocr_values) if ocr_values else None),
            average_direct_text_quality=(sum(direct_values) / len(direct_values) if direct_values else None),
            open_seconds=sum(item.open_seconds for item in ordered_extractions),
            direct_text_seconds=sum(item.direct_text_seconds for item in ordered_extractions),
            render_seconds=sum(item.render_seconds for item in ordered_extractions),
            ocr_seconds=sum(item.ocr_seconds for item in ordered_extractions),
            total_seconds=sum(item.total_seconds for item in ordered_extractions),
            render_dpi=first_extraction.render_dpi,
            ocr_language=first_extraction.ocr_language,
            ocr_config=first_extraction.ocr_config,
            combined_text=combined_text,
            pages=pages,
            warnings=[warning for item in ordered_extractions for warning in item.warnings],
            errors=[error for item in ordered_extractions for error in item.errors],
            completed_at=utc_now(),
        )
        return group_document, merged

    def _analyze_group(
        self,
        documents: list[UploadedDocument],
        *,
        force: bool,
    ) -> LeaseAnalysisResult | RegistryAnalysisResult:
        if len(documents) == 1:
            return self.analyze_document(
                conversation_id=documents[0].conversation_id,
                document_id=documents[0].document_id,
                force=force,
            )
        extractions = [self._load_extraction(document) for document in documents]
        group_document, merged = self._merge_group(documents, extractions)
        source_ids = [item.document_id for item in sorted(documents, key=self._natural_document_key)]
        if group_document.document_type != DocumentType.REGISTRY:
            raise ValueError("여러 계약서는 자동 병합하지 않습니다.")
        result = analyze_registry(document=group_document, extraction=merged).model_copy(
            update={"source_document_ids": source_ids}
        )
        stored = self.analysis_storage.save_registry(group_document, result)
        partial = merged.processing_status == DocumentProcessingStatus.PARTIAL or bool(stored.errors)
        for document in documents:
            self._mark_completed(
                document,
                result_path=stored.analysis_result_path,
                warnings=stored.warnings,
                partial=partial,
            )
        return stored

    def analyze_conversation_documents(
        self,
        *,
        conversation_id: str,
        document_ids: list[str] | None = None,
        force: bool = False,
    ) -> ConversationDocumentAnalysisResponse:
        all_documents = self.repository.list_documents(conversation_id)
        allowed_ids = set(document_ids or [])
        selected = [
            document
            for document in all_documents
            if document.document_type in {
                DocumentType.LEASE_CONTRACT,
                DocumentType.REGISTRY,
                }
            and (not allowed_ids or document.document_id in allowed_ids)
        ]
        if allowed_ids:
            missing = allowed_ids - {document.document_id for document in selected}
            if missing:
                raise ValueError(
                    "분석할 수 없거나 현재 상담에 없는 document_id: "
                    + ", ".join(sorted(missing))
                )
        if not selected:
            raise ValueError(
                "현재 상담에 분석 가능한 계약서 또는 등기부등본이 없습니다."
            )

        lease_results: list[LeaseAnalysisResult] = []
        registry_results: list[RegistryAnalysisResult] = []
        warnings: list[str] = []
        by_type = {
            document_type: [
                document for document in selected
                if document.document_type == document_type
            ]
            for document_type in (
                DocumentType.LEASE_CONTRACT,
                DocumentType.REGISTRY,
                )
        }
        lease_documents = by_type[DocumentType.LEASE_CONTRACT]
        if lease_documents:
            if len(lease_documents) > 1:
                warnings.append("계약서가 여러 개라 가장 최근 업로드 문서만 분석했습니다.")
            latest_document = sorted(lease_documents, key=lambda item: item.uploaded_at)[-1]
            lease_results.append(self._analyze_group([latest_document], force=force))
        registry_documents = by_type[DocumentType.REGISTRY]
        if registry_documents:
            registry_results.append(self._analyze_group(registry_documents, force=force))
            if len(registry_documents) > 1:
                warnings.append(f"등기부 {len(registry_documents)}개 파일을 페이지 순서대로 병합했습니다.")
        latest_lease = lease_results[-1] if lease_results else None
        latest_registry = registry_results[-1] if registry_results else None
        comparison = compare_documents(
            conversation_id=conversation_id,
            lease=latest_lease,
            registry=latest_registry,
        )
        stored_comparison = self.analysis_storage.save_comparison(comparison)
        warnings.extend(stored_comparison.warnings)
        return ConversationDocumentAnalysisResponse(
            lease_analyses=lease_results,
            registry_analyses=registry_results,
            comparison=stored_comparison,
            warnings=warnings,
        )
