"""업로드 파일의 이름·크기·확장자·MIME·실제 시그니처를 검사한다."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.documents.models import DocumentFormat

DEFAULT_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
GENERIC_CONTENT_TYPES = {
    "",
    "application/octet-stream",
    "binary/octet-stream",
}

FORMAT_EXTENSIONS: dict[DocumentFormat, frozenset[str]] = {
    DocumentFormat.PDF: frozenset({".pdf"}),
}

CANONICAL_EXTENSIONS: dict[DocumentFormat, str] = {
    DocumentFormat.PDF: ".pdf",
}

CANONICAL_CONTENT_TYPES: dict[DocumentFormat, str] = {
    DocumentFormat.PDF: "application/pdf",
}

ACCEPTED_CONTENT_TYPES: dict[DocumentFormat, frozenset[str]] = {
    DocumentFormat.PDF: frozenset({"application/pdf"}),
}


class DocumentValidationError(ValueError):
    """업로드 문서가 허용 기준을 통과하지 못했을 때 발생한다."""


class EmptyDocumentError(DocumentValidationError):
    pass


class DocumentTooLargeError(DocumentValidationError):
    pass


class UnsupportedDocumentFormatError(DocumentValidationError):
    pass


class DocumentTypeMismatchError(DocumentValidationError):
    pass


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    original_filename: str
    safe_filename: str
    detected_format: DocumentFormat
    canonical_extension: str
    canonical_content_type: str
    declared_content_type: str | None
    size_bytes: int
    sha256: str
    data: bytes


def sanitize_filename(filename: str) -> str:
    if not filename or not filename.strip():
        raise DocumentValidationError("파일명이 비어 있습니다.")

    normalized = unicodedata.normalize("NFKC", filename.strip())
    basename = normalized.replace("\\", "/").split("/")[-1]
    basename = "".join(
        character
        if character.isalnum() or character in {" ", ".", "_", "-", "(", ")", "[", "]"}
        else "_"
        for character in basename
    )
    basename = re.sub(r"\s+", " ", basename)
    basename = re.sub(r"_+", "_", basename)
    basename = basename.strip(" ._")

    if not basename:
        raise DocumentValidationError("안전한 파일명을 만들 수 없습니다.")

    if len(basename) > 180:
        suffix = Path(basename).suffix[:12]
        stem_limit = 180 - len(suffix)
        basename = f"{Path(basename).stem[:stem_limit]}{suffix}"

    return basename


def _detect_format(data: bytes) -> DocumentFormat:
    if data.startswith(b"%PDF-"):
        return DocumentFormat.PDF
    raise UnsupportedDocumentFormatError("PDF 파일만 업로드할 수 있습니다.")


def _format_from_extension(filename: str) -> DocumentFormat:
    extension = Path(filename).suffix.lower()
    for document_format, extensions in FORMAT_EXTENSIONS.items():
        if extension in extensions:
            return document_format
    raise UnsupportedDocumentFormatError(
        "허용되지 않는 확장자입니다. PDF 파일만 업로드할 수 있습니다."
    )


def normalize_content_type(content_type: str | None) -> str:
    if content_type is None:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


def validate_upload_bytes(
    *,
    filename: str,
    content_type: str | None,
    data: bytes,
    max_size_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
) -> ValidatedUpload:
    if max_size_bytes <= 0:
        raise ValueError("max_size_bytes는 1 이상이어야 합니다.")
    if not data:
        raise EmptyDocumentError("빈 파일은 업로드할 수 없습니다.")
    if len(data) > max_size_bytes:
        raise DocumentTooLargeError(
            f"파일 크기가 허용 한도 {max_size_bytes}바이트를 초과했습니다."
        )

    safe_filename = sanitize_filename(filename)
    extension_format = _format_from_extension(safe_filename)
    detected_format = _detect_format(data)

    if extension_format != detected_format:
        raise DocumentTypeMismatchError(
            "파일 확장자와 실제 파일 형식이 일치하지 않습니다."
        )

    normalized_content_type = normalize_content_type(content_type)
    if (
        normalized_content_type not in GENERIC_CONTENT_TYPES
        and normalized_content_type not in ACCEPTED_CONTENT_TYPES[detected_format]
    ):
        raise DocumentTypeMismatchError(
            "선언된 MIME type과 실제 파일 형식이 일치하지 않습니다."
        )

    original_filename = filename.strip()
    if len(original_filename) > 512:
        original_filename = original_filename[:512]

    return ValidatedUpload(
        original_filename=original_filename,
        safe_filename=safe_filename,
        detected_format=detected_format,
        canonical_extension=CANONICAL_EXTENSIONS[detected_format],
        canonical_content_type=CANONICAL_CONTENT_TYPES[detected_format],
        declared_content_type=normalized_content_type or None,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data=data,
    )


def read_stream_limited(
    stream: BinaryIO,
    *,
    max_size_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    chunk_size: int = 1024 * 1024,
) -> bytes:
    if max_size_bytes <= 0:
        raise ValueError("max_size_bytes는 1 이상이어야 합니다.")
    if chunk_size <= 0:
        raise ValueError("chunk_size는 1 이상이어야 합니다.")

    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = stream.read(min(chunk_size, max_size_bytes - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > max_size_bytes:
            raise DocumentTooLargeError(
                f"파일 크기가 허용 한도 {max_size_bytes}바이트를 초과했습니다."
            )
        chunks.append(chunk)

    data = b"".join(chunks)
    if not data:
        raise EmptyDocumentError("빈 파일은 업로드할 수 없습니다.")
    return data
