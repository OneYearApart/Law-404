"""PDF를 열고 텍스트 레이어를 직접 읽거나 OCR용 이미지로 렌더링한다."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from PIL import Image


class PDFExtractionError(RuntimeError):
    pass


class EncryptedPDFError(PDFExtractionError):
    pass


class CorruptedPDFError(PDFExtractionError):
    pass


class TooManyPagesError(PDFExtractionError):
    pass


class RenderedPageTooLargeError(PDFExtractionError):
    pass


@dataclass(slots=True)
class OpenedPDF:
    document: Any
    open_seconds: float
    page_count: int


def _pymupdf():
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        try:
            import fitz as pymupdf

            return pymupdf
        except ImportError as error:
            raise PDFExtractionError("PyMuPDF를 불러오지 못했습니다.") from error


def open_pdf(path: Path, *, max_pages: int = 100) -> OpenedPDF:
    if max_pages <= 0:
        raise ValueError("max_pages는 1 이상이어야 합니다.")

    pymupdf = _pymupdf()
    started = perf_counter()
    try:
        document = pymupdf.open(path)
    except Exception as error:
        raise CorruptedPDFError(
            "PDF 파일을 열지 못했습니다. 파일이 손상됐을 수 있습니다."
        ) from error
    open_seconds = perf_counter() - started

    try:
        if bool(getattr(document, "needs_pass", False)):
            raise EncryptedPDFError(
                "비밀번호가 필요한 암호화 PDF는 현재 처리할 수 없습니다."
            )
        page_count = int(document.page_count)
        if page_count <= 0:
            raise CorruptedPDFError("PDF에 처리할 페이지가 없습니다.")
        if page_count > max_pages:
            raise TooManyPagesError(
                f"PDF 페이지 수 {page_count}개가 허용 한도 {max_pages}개를 초과했습니다."
            )
        return OpenedPDF(
            document=document,
            open_seconds=open_seconds,
            page_count=page_count,
        )
    except Exception:
        document.close()
        raise


def extract_pdf_page_text(page: Any) -> tuple[str, float]:
    """PyMuPDF 텍스트 레이어에서 페이지 문자열을 직접 추출한다."""

    started = perf_counter()
    try:
        text = page.get_text("text", sort=True) or ""
    except Exception as error:
        raise PDFExtractionError(
            f"PDF {int(page.number) + 1}페이지의 텍스트 레이어를 읽지 못했습니다."
        ) from error
    return text.strip(), perf_counter() - started


def render_pdf_page(
    page: Any,
    *,
    dpi: int = 300,
    max_pixels: int = 60_000_000,
) -> tuple[Image.Image, float]:
    if dpi < 72:
        raise ValueError("dpi는 72 이상이어야 합니다.")
    if max_pixels <= 0:
        raise ValueError("max_pixels는 1 이상이어야 합니다.")

    pymupdf = _pymupdf()
    started = perf_counter()
    try:
        pixmap = page.get_pixmap(
            dpi=dpi,
            colorspace=pymupdf.csRGB,
            alpha=False,
            annots=True,
        )
        pixel_count = int(pixmap.width) * int(pixmap.height)
        if pixel_count > max_pixels:
            raise RenderedPageTooLargeError(
                f"렌더링 이미지가 {pixel_count:,}픽셀로 허용 한도 "
                f"{max_pixels:,}픽셀을 초과했습니다."
            )
        image = Image.frombytes(
            "RGB",
            (pixmap.width, pixmap.height),
            pixmap.samples,
        )
    except RenderedPageTooLargeError:
        raise
    except Exception as error:
        raise PDFExtractionError(
            f"PDF {int(page.number) + 1}페이지를 이미지로 변환하지 못했습니다."
        ) from error

    return image, perf_counter() - started
