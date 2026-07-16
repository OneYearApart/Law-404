from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.consultation.a_part.document_service import APartDocumentUploadService
from app.consultation.a_part.models import create_conversation_state
from app.consultation.a_part.service import APartConversationService
from app.consultation.a_part.store import ConversationNotFoundError, MemoryConversationStore
from app.documents.models import DocumentFormat, DocumentType
from app.documents.service import DocumentUploadService
from app.documents.storage import DuplicateDocumentTypeConflictError
from app.documents.validation import (
    DocumentTooLargeError,
    DocumentTypeMismatchError,
    EmptyDocumentError,
    UnsupportedDocumentFormatError,
    read_stream_limited,
    validate_upload_bytes,
)

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"png-body"
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"jpeg-body"
WEBP_BYTES = b"RIFF" + (8).to_bytes(4, "little") + b"WEBP" + b"data"


def validate_pdf_only_upload() -> None:
    result = validate_upload_bytes(
        filename="계약서.pdf",
        content_type="application/pdf",
        data=PDF_BYTES,
    )
    assert result.detected_format == DocumentFormat.PDF
    assert result.size_bytes == len(PDF_BYTES)
    assert len(result.sha256) == 64

    for filename, content_type, data in (
        ("등기부.png", "image/png", PNG_BYTES),
        ("이체내역.jpg", "image/jpeg", JPEG_BYTES),
        ("위임장.webp", "image/webp", WEBP_BYTES),
    ):
        try:
            validate_upload_bytes(filename=filename, content_type=content_type, data=data)
        except UnsupportedDocumentFormatError:
            pass
        else:
            raise AssertionError(f"PDF가 아닌 파일을 허용했습니다: {filename}")

    generic = validate_upload_bytes(
        filename="계약서.pdf",
        content_type="application/octet-stream",
        data=PDF_BYTES,
    )
    assert generic.canonical_content_type == "application/pdf"

    sanitized = validate_upload_bytes(
        filename="../../계약서<>최종.pdf",
        content_type="application/pdf",
        data=PDF_BYTES,
    )
    assert all(token not in sanitized.safe_filename for token in ("/", "\\", "<", ">"))
    assert sanitized.safe_filename.endswith(".pdf")

    invalid_cases = [
        (EmptyDocumentError, dict(filename="빈파일.pdf", content_type="application/pdf", data=b"")),
        (DocumentTooLargeError, dict(filename="큰파일.pdf", content_type="application/pdf", data=PDF_BYTES, max_size_bytes=8)),
        ((DocumentTypeMismatchError, UnsupportedDocumentFormatError), dict(filename="위장파일.pdf", content_type="application/pdf", data=PNG_BYTES)),
        (DocumentTypeMismatchError, dict(filename="계약서.pdf", content_type="image/png", data=PDF_BYTES)),
        (UnsupportedDocumentFormatError, dict(filename="문서.txt", content_type="text/plain", data=b"plain text")),
    ]
    for expected_error, kwargs in invalid_cases:
        try:
            validate_upload_bytes(**kwargs)
        except expected_error:
            pass
        else:
            raise AssertionError(f"업로드 차단 검증 실패: {kwargs['filename']}")

    try:
        read_stream_limited(BytesIO(PDF_BYTES), max_size_bytes=8, chunk_size=4)
    except DocumentTooLargeError:
        pass
    else:
        raise AssertionError("스트림 크기 제한을 초과했는데 통과했습니다.")


def validate_storage() -> None:
    with TemporaryDirectory() as directory:
        service = DocumentUploadService(storage_root=Path(directory))
        conversation_id = "conversation-test-001"

        first = service.upload_bytes(
            conversation_id=conversation_id,
            document_type=DocumentType.LEASE_CONTRACT,
            filename="../../내 계약서 최종본.pdf",
            content_type="application/pdf",
            data=PDF_BYTES,
        )
        assert first.processing_status.value == "uploaded"
        assert first.is_duplicate is False
        assert first.safe_filename == "내 계약서 최종본.pdf"
        assert first.stored_filename == f"{first.document_id}.pdf"
        assert first.stored_path.startswith(f"{conversation_id}/")
        assert service.read_bytes(conversation_id, first.document_id) == PDF_BYTES

        duplicate = service.upload_bytes(
            conversation_id=conversation_id,
            document_type=DocumentType.LEASE_CONTRACT,
            filename="이름만다른계약서.pdf",
            content_type="application/pdf",
            data=PDF_BYTES,
        )
        assert duplicate.is_duplicate is True
        assert duplicate.document_id == first.document_id
        assert len(service.list_documents(conversation_id)) == 1

        second = service.upload_bytes(
            conversation_id=conversation_id,
            document_type=DocumentType.LEASE_CONTRACT,
            filename="다른계약서.pdf",
            content_type="application/pdf",
            data=PDF_BYTES + b"\nsecond",
        )
        assert second.document_id != first.document_id

        try:
            service.upload_bytes(
                conversation_id=conversation_id,
                document_type=DocumentType.REGISTRY,
                filename="같은파일.pdf",
                content_type="application/pdf",
                data=PDF_BYTES,
            )
        except DuplicateDocumentTypeConflictError:
            pass
        else:
            raise AssertionError("같은 파일을 다른 문서 유형으로 중복 등록했습니다.")

        removed = service.delete(conversation_id, second.document_id)
        assert removed.document_id == second.document_id


def validate_conversation_link() -> None:
    with TemporaryDirectory() as directory:
        store = MemoryConversationStore()
        conversation_service = APartConversationService(store=store)
        state = create_conversation_state("q01_owner_proxy")
        store.create(state)

        service = APartDocumentUploadService(
            upload_service=DocumentUploadService(storage_root=Path(directory)),
            conversation_service=conversation_service,
        )
        contract = service.upload_bytes(
            conversation_id=state.conversation_id,
            document_type=DocumentType.LEASE_CONTRACT,
            filename="임대차계약서.pdf",
            content_type="application/pdf",
            data=PDF_BYTES,
        )
        assert contract.conversation_document_count == 1
        assert len(conversation_service.get_state(state.conversation_id).documents) == 1

        duplicate = service.upload_bytes(
            conversation_id=state.conversation_id,
            document_type=DocumentType.LEASE_CONTRACT,
            filename="같은계약서.pdf",
            content_type="application/pdf",
            data=PDF_BYTES,
        )
        assert duplicate.document.is_duplicate is True
        assert duplicate.conversation_document_count == 1

        registry = service.upload_bytes(
            conversation_id=state.conversation_id,
            document_type=DocumentType.REGISTRY,
            filename="등기부등본.pdf",
            content_type="application/pdf",
            data=PDF_BYTES + b"-registry",
        )
        assert registry.conversation_document_count == 2
        assert {item.document_type for item in registry.state.documents} == {
            DocumentType.LEASE_CONTRACT,
            DocumentType.REGISTRY,
        }

        try:
            service.upload_bytes(
                conversation_id="missing-conversation",
                document_type=DocumentType.OTHER,
                filename="기타.pdf",
                content_type="application/pdf",
                data=PDF_BYTES,
            )
        except ConversationNotFoundError:
            pass
        else:
            raise AssertionError("존재하지 않는 conversation_id 업로드가 실패하지 않았습니다.")


def main() -> None:
    checks = [
        ("PDF 형식·크기·MIME·파일명 검증", validate_pdf_only_upload),
        ("UUID 안전 저장·메타데이터·중복 처리", validate_storage),
        ("ConversationState PDF 문서 연결", validate_conversation_link),
    ]
    for label, check in checks:
        check()
        print("PASS:", label)

    assert list(DocumentFormat) == [DocumentFormat.PDF]
    print()
    print("=" * 100)
    print("A파트 PDF 전용 문서 업로드 전체 검증")
    print("-" * 100)
    print(f"지원 문서 유형: {len(DocumentType)}개")
    print("허용 파일 형식: PDF")
    print("PNG·JPEG·WEBP 업로드 차단: PASS")
    print("빈 파일 차단: PASS")
    print("파일 크기 제한: PASS")
    print("확장자·MIME·실제 시그니처 대조: PASS")
    print("경로 조작 파일명 정리: PASS")
    print("UUID 내부 저장명: PASS")
    print("상담별 저장 폴더 분리: PASS")
    print("SHA-256 중복 파일 재사용: PASS")
    print("ConversationState PDF 문서 연결: PASS")
    print("중복 문서 재연결 방지: PASS")
    print("존재하지 않는 conversation_id 차단: PASS")
    print("최종 판정: PASS")


if __name__ == "__main__":
    main()
