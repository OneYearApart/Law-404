"""PDF는 직접 텍스트 추출을 우선하고 부족한 페이지만 OCR한다."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from PIL import Image

from backend.app.documents.extraction_models import (
    EXTRACTION_VERSION,
    DocumentExtractionResult,
    ExtractionMethod,
    PDFExtractionStrategy,
    PageExtractionResult,
    PageExtractionStatus,
)
from backend.app.documents.extraction_storage import DocumentExtractionStorage
from backend.app.documents.models import (
    DocumentFormat,
    DocumentProcessingStatus,
    UploadedDocument,
)
from backend.app.documents.ocr import AdaptiveTesseractOCRProvider, OCRProvider
from backend.app.documents.pdf_extractor import (
    extract_pdf_page_text,
    open_pdf,
    render_pdf_page,
)
from backend.app.documents.storage import FileDocumentRepository
from backend.app.documents.text_metrics import normalize_text
from backend.app.documents.text_quality import evaluate_direct_text_quality


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentExtractionService:
    """PDF는 텍스트 레이어를 먼저 사용하고 이미지 페이지에만 OCR을 적용한다."""

    def __init__(
        self,
        *,
        repository: FileDocumentRepository,
        ocr_provider: OCRProvider | None = None,
        result_storage: DocumentExtractionStorage | None = None,
        render_dpi: int = 300,
        max_pages: int = 100,
        max_pixels: int = 60_000_000,
        extraction_version: str = EXTRACTION_VERSION,
        pdf_strategy: PDFExtractionStrategy | str = (
            PDFExtractionStrategy.DIRECT_TEXT_FIRST
        ),
        minimum_direct_characters: int = 20,
        minimum_direct_quality_score: float = 0.60,
    ) -> None:
        if render_dpi < 72:
            raise ValueError("render_dpi는 72 이상이어야 합니다.")
        if max_pages <= 0:
            raise ValueError("max_pages는 1 이상이어야 합니다.")
        if max_pixels <= 0:
            raise ValueError("max_pixels는 1 이상이어야 합니다.")
        if minimum_direct_characters <= 0:
            raise ValueError("minimum_direct_characters는 1 이상이어야 합니다.")
        if not 0.0 <= minimum_direct_quality_score <= 1.0:
            raise ValueError(
                "minimum_direct_quality_score는 0.0 이상 1.0 이하여야 합니다."
            )

        self.repository = repository
        self.ocr_provider = ocr_provider or AdaptiveTesseractOCRProvider()
        self.result_storage = result_storage or DocumentExtractionStorage(
            repository
        )
        self.render_dpi = render_dpi
        self.max_pages = max_pages
        self.max_pixels = max_pixels
        self.extraction_version = extraction_version
        self.pdf_strategy = PDFExtractionStrategy(pdf_strategy)
        self.minimum_direct_characters = minimum_direct_characters
        self.minimum_direct_quality_score = minimum_direct_quality_score

    @staticmethod
    def _document_method(
        pages: list[PageExtractionResult],
    ) -> ExtractionMethod:
        methods = {
            page.extraction_method
            for page in pages
            if page.status == PageExtractionStatus.COMPLETED
        }
        if not methods:
            return ExtractionMethod.NONE
        if methods == {ExtractionMethod.DIRECT_TEXT}:
            return ExtractionMethod.DIRECT_TEXT
        if methods == {ExtractionMethod.OCR}:
            return ExtractionMethod.OCR
        return ExtractionMethod.MIXED

    @staticmethod
    def _status(
        *,
        successful: int,
        failed: int,
    ) -> DocumentProcessingStatus:
        if successful > 0 and failed == 0:
            return DocumentProcessingStatus.COMPLETED
        if successful > 0 and failed > 0:
            return DocumentProcessingStatus.PARTIAL
        return DocumentProcessingStatus.FAILED

    @staticmethod
    def _combine_pages(pages: list[PageExtractionResult]) -> str:
        sections = [
            f"--- 페이지 {page.page_number} ---\n{page.text.strip()}"
            for page in pages
            if page.status == PageExtractionStatus.COMPLETED
            and page.text.strip()
        ]
        return "\n\n".join(sections).strip()

    @staticmethod
    def _average_confidence(
        pages: list[PageExtractionResult],
    ) -> float | None:
        values = [
            page.ocr_confidence
            for page in pages
            if page.extraction_method == ExtractionMethod.OCR
            and page.ocr_confidence is not None
        ]
        return sum(values) / len(values) if values else None

    @staticmethod
    def _average_direct_quality(
        pages: list[PageExtractionResult],
    ) -> float | None:
        values = [
            page.direct_text_quality_score
            for page in pages
            if page.extraction_method == ExtractionMethod.DIRECT_TEXT
            and page.direct_text_quality_score is not None
        ]
        return sum(values) / len(values) if values else None

    @staticmethod
    def _method_count(
        pages: list[PageExtractionResult],
        method: ExtractionMethod,
    ) -> int:
        return sum(
            page.status == PageExtractionStatus.COMPLETED
            and page.extraction_method == method
            for page in pages
        )

    def _run_page_ocr(
        self,
        *,
        page_number: int,
        image: Image.Image,
        direct_text: str = "",
        direct_text_seconds: float = 0.0,
        direct_quality_score: float | None = None,
        direct_quality_reasons: list[str] | None = None,
        render_seconds: float = 0.0,
        fallback_to_ocr: bool = False,
    ) -> PageExtractionResult:
        quality_reasons = list(direct_quality_reasons or [])
        warnings = (
            ["PDF 직접 추출 결과가 부족해 Tesseract OCR로 전환했습니다."]
            if fallback_to_ocr
            else []
        )
        warnings.extend(quality_reasons if fallback_to_ocr else [])

        try:
            ocr_result = self.ocr_provider.recognize(image)
            postprocess_started = perf_counter()
            ocr_text = normalize_text(
                ocr_result.text,
                keep_line_breaks=True,
            )
            postprocess_seconds = perf_counter() - postprocess_started
            total_seconds = (
                direct_text_seconds
                + render_seconds
                + ocr_result.elapsed_seconds
                + postprocess_seconds
            )

            if not ocr_text:
                return PageExtractionResult(
                    page_number=page_number,
                    status=PageExtractionStatus.FAILED,
                    extraction_method=ExtractionMethod.OCR,
                    text="",
                    direct_text=direct_text,
                    ocr_text="",
                    direct_text_character_count=len(direct_text),
                    direct_text_quality_score=direct_quality_score,
                    direct_text_quality_reasons=quality_reasons,
                    fallback_to_ocr=fallback_to_ocr,
                    ocr_confidence=ocr_result.confidence,
                    direct_text_seconds=direct_text_seconds,
                    render_seconds=render_seconds,
                    ocr_seconds=ocr_result.elapsed_seconds,
                    postprocess_seconds=postprocess_seconds,
                    total_seconds=total_seconds,
                    image_width=image.width,
                    image_height=image.height,
                    warnings=[*warnings, *ocr_result.warnings],
                    error_code="empty_ocr_text",
                    error_message="OCR을 실행했지만 텍스트를 얻지 못했습니다.",
                )

            return PageExtractionResult(
                page_number=page_number,
                status=PageExtractionStatus.COMPLETED,
                extraction_method=ExtractionMethod.OCR,
                text=ocr_text,
                direct_text=direct_text,
                ocr_text=ocr_text,
                character_count=len(ocr_text),
                direct_text_character_count=len(direct_text),
                direct_text_quality_score=direct_quality_score,
                direct_text_quality_reasons=quality_reasons,
                fallback_to_ocr=fallback_to_ocr,
                ocr_confidence=ocr_result.confidence,
                direct_text_seconds=direct_text_seconds,
                render_seconds=render_seconds,
                ocr_seconds=ocr_result.elapsed_seconds,
                postprocess_seconds=postprocess_seconds,
                total_seconds=total_seconds,
                image_width=image.width,
                image_height=image.height,
                warnings=[*warnings, *ocr_result.warnings],
            )
        except Exception as error:
            return PageExtractionResult(
                page_number=page_number,
                status=PageExtractionStatus.FAILED,
                extraction_method=ExtractionMethod.OCR,
                direct_text=direct_text,
                direct_text_character_count=len(direct_text),
                direct_text_quality_score=direct_quality_score,
                direct_text_quality_reasons=quality_reasons,
                fallback_to_ocr=fallback_to_ocr,
                direct_text_seconds=direct_text_seconds,
                render_seconds=render_seconds,
                total_seconds=direct_text_seconds + render_seconds,
                image_width=image.width,
                image_height=image.height,
                warnings=warnings,
                error_code=error.__class__.__name__,
                error_message=str(error),
            )
        finally:
            image.close()

    def _direct_page_result(
        self,
        *,
        page_number: int,
        text: str,
        direct_text_seconds: float,
        quality_score: float,
        quality_reasons: list[str],
    ) -> PageExtractionResult:
        postprocess_started = perf_counter()
        normalized = normalize_text(text, keep_line_breaks=True)
        postprocess_seconds = perf_counter() - postprocess_started
        return PageExtractionResult(
            page_number=page_number,
            status=PageExtractionStatus.COMPLETED,
            extraction_method=ExtractionMethod.DIRECT_TEXT,
            text=normalized,
            direct_text=normalized,
            character_count=len(normalized),
            direct_text_character_count=len(normalized),
            direct_text_quality_score=quality_score,
            direct_text_quality_reasons=quality_reasons,
            direct_text_seconds=direct_text_seconds,
            postprocess_seconds=postprocess_seconds,
            total_seconds=direct_text_seconds + postprocess_seconds,
        )

    def _extract_pdf(
        self,
        path: Path,
    ) -> tuple[list[PageExtractionResult], float, int, list[str]]:
        opened = open_pdf(path, max_pages=self.max_pages)
        pages: list[PageExtractionResult] = []
        warnings: list[str] = []
        try:
            for index in range(opened.page_count):
                page = opened.document[index]
                page_number = index + 1
                direct_text = ""
                direct_text_seconds = 0.0
                quality_score: float | None = None
                quality_reasons: list[str] = []

                if self.pdf_strategy == PDFExtractionStrategy.DIRECT_TEXT_FIRST:
                    try:
                        direct_text, direct_text_seconds = extract_pdf_page_text(page)
                        quality = evaluate_direct_text_quality(
                            direct_text,
                            minimum_compact_characters=(
                                self.minimum_direct_characters
                            ),
                            minimum_score=self.minimum_direct_quality_score,
                        )
                        quality_score = quality.score
                        quality_reasons = list(quality.reasons)
                        if quality.usable:
                            pages.append(
                                self._direct_page_result(
                                    page_number=page_number,
                                    text=direct_text,
                                    direct_text_seconds=direct_text_seconds,
                                    quality_score=quality.score,
                                    quality_reasons=quality_reasons,
                                )
                            )
                            continue
                    except Exception as error:
                        quality_reasons = [
                            "PDF 텍스트 레이어 직접 추출 중 오류가 발생해 OCR로 전환합니다.",
                            f"{error.__class__.__name__}: {error}",
                        ]

                try:
                    image, render_seconds = render_pdf_page(
                        page,
                        dpi=self.render_dpi,
                        max_pixels=self.max_pixels,
                    )
                except Exception as error:
                    pages.append(
                        PageExtractionResult(
                            page_number=page_number,
                            status=PageExtractionStatus.FAILED,
                            extraction_method=ExtractionMethod.OCR,
                            direct_text=direct_text,
                            direct_text_character_count=len(direct_text),
                            direct_text_quality_score=quality_score,
                            direct_text_quality_reasons=quality_reasons,
                            fallback_to_ocr=(
                                self.pdf_strategy
                                == PDFExtractionStrategy.DIRECT_TEXT_FIRST
                            ),
                            direct_text_seconds=direct_text_seconds,
                            total_seconds=direct_text_seconds,
                            warnings=quality_reasons,
                            error_code=error.__class__.__name__,
                            error_message=str(error),
                        )
                    )
                    continue

                pages.append(
                    self._run_page_ocr(
                        page_number=page_number,
                        image=image,
                        direct_text=direct_text,
                        direct_text_seconds=direct_text_seconds,
                        direct_quality_score=quality_score,
                        direct_quality_reasons=quality_reasons,
                        render_seconds=render_seconds,
                        fallback_to_ocr=(
                            self.pdf_strategy
                            == PDFExtractionStrategy.DIRECT_TEXT_FIRST
                        ),
                    )
                )
        finally:
            opened.document.close()
        return pages, opened.open_seconds, opened.page_count, warnings

    def _failed_result(
        self,
        *,
        document: UploadedDocument,
        started_at: datetime,
        started_counter: float,
        error: Exception,
    ) -> DocumentExtractionResult:
        return DocumentExtractionResult(
            extraction_version=self.extraction_version,
            document_id=document.document_id,
            conversation_id=document.conversation_id,
            source_sha256=document.sha256,
            processing_status=DocumentProcessingStatus.FAILED,
            extraction_method=ExtractionMethod.NONE,
            pdf_strategy=self.pdf_strategy,
            detected_format=document.detected_format.value,
            page_count=0,
            successful_page_count=0,
            failed_page_count=0,
            direct_text_page_count=0,
            ocr_page_count=0,
            text_character_count=0,
            average_ocr_confidence=None,
            average_direct_text_quality=None,
            total_seconds=perf_counter() - started_counter,
            render_dpi=self.render_dpi,
            ocr_language=self.ocr_provider.language,
            ocr_config=self.ocr_provider.config,
            combined_text="",
            pages=[],
            errors=[f"{error.__class__.__name__}: {error}"],
            started_at=started_at,
            completed_at=utc_now(),
        )

    def _update_document(
        self,
        document: UploadedDocument,
        result: DocumentExtractionResult,
    ) -> UploadedDocument:
        updated = document.model_copy(
            update={
                "processing_status": result.processing_status,
                "extraction_method": result.extraction_method.value,
                "extraction_version": result.extraction_version,
                "page_count": result.page_count,
                "successful_page_count": result.successful_page_count,
                "failed_page_count": result.failed_page_count,
                "direct_text_page_count": result.direct_text_page_count,
                "ocr_page_count": result.ocr_page_count,
                "text_character_count": result.text_character_count,
                "average_ocr_confidence": result.average_ocr_confidence,
                "average_direct_text_quality": (
                    result.average_direct_text_quality
                ),
                "extraction_total_seconds": result.total_seconds,
                "extraction_result_path": result.extraction_result_path,
                "extracted_text_path": result.extracted_text_path,
                "extraction_warnings": [
                    *result.warnings,
                    *result.errors,
                ],
                "extraction_error": (
                    result.errors[0]
                    if result.processing_status == DocumentProcessingStatus.FAILED
                    and result.errors
                    else None
                ),
                "extraction_started_at": result.started_at,
                "extraction_completed_at": result.completed_at,
            }
        )
        return self.repository.update_document(updated)

    def extract(
        self,
        *,
        conversation_id: str,
        document_id: str,
        force: bool = False,
    ) -> DocumentExtractionResult:
        document = self.repository.get(conversation_id, document_id)

        if not force:
            current = self.result_storage.current_result(
                document,
                extraction_version=self.extraction_version,
            )
            if current is not None:
                self._update_document(document, current)
                return current

        started_at = utc_now()
        started_counter = perf_counter()
        extracting_document = document.model_copy(
            update={
                "processing_status": DocumentProcessingStatus.EXTRACTING,
                "extraction_version": self.extraction_version,
                "extraction_started_at": started_at,
                "extraction_completed_at": None,
                "extraction_error": None,
                "extraction_warnings": [],
            }
        )
        self.repository.update_document(extracting_document)
        path = self.repository.resolve_path(extracting_document)

        try:
            if extracting_document.detected_format != DocumentFormat.PDF:
                raise ValueError("PDF 문서만 추출할 수 있습니다.")
            pages, open_seconds, page_count, warnings = self._extract_pdf(path)

            successful = sum(
                page.status == PageExtractionStatus.COMPLETED
                for page in pages
            )
            failed = sum(
                page.status == PageExtractionStatus.FAILED
                for page in pages
            )
            combined_text = self._combine_pages(pages)
            page_errors = [
                f"{page.page_number}페이지: {page.error_message}"
                for page in pages
                if page.error_message
            ]
            page_warnings = [
                f"{page.page_number}페이지: {warning}"
                for page in pages
                for warning in page.warnings
            ]
            result = DocumentExtractionResult(
                extraction_version=self.extraction_version,
                document_id=extracting_document.document_id,
                conversation_id=extracting_document.conversation_id,
                source_sha256=extracting_document.sha256,
                processing_status=self._status(
                    successful=successful,
                    failed=failed,
                ),
                extraction_method=self._document_method(pages),
                pdf_strategy=self.pdf_strategy,
                detected_format=extracting_document.detected_format.value,
                page_count=page_count,
                successful_page_count=successful,
                failed_page_count=failed,
                direct_text_page_count=self._method_count(
                    pages,
                    ExtractionMethod.DIRECT_TEXT,
                ),
                ocr_page_count=self._method_count(
                    pages,
                    ExtractionMethod.OCR,
                ),
                text_character_count=len(combined_text),
                average_ocr_confidence=self._average_confidence(pages),
                average_direct_text_quality=(
                    self._average_direct_quality(pages)
                ),
                open_seconds=open_seconds,
                direct_text_seconds=sum(
                    page.direct_text_seconds for page in pages
                ),
                render_seconds=sum(page.render_seconds for page in pages),
                ocr_seconds=sum(page.ocr_seconds for page in pages),
                total_seconds=perf_counter() - started_counter,
                render_dpi=self.render_dpi,
                ocr_language=self.ocr_provider.language,
                ocr_config=self.ocr_provider.config,
                combined_text=combined_text,
                pages=pages,
                warnings=[*warnings, *page_warnings],
                errors=page_errors,
                started_at=started_at,
                completed_at=utc_now(),
            )
        except Exception as error:
            result = self._failed_result(
                document=extracting_document,
                started_at=started_at,
                started_counter=started_counter,
                error=error,
            )

        stored_result = self.result_storage.save(
            extracting_document,
            result,
        )
        self._update_document(extracting_document, stored_result)
        return stored_result
