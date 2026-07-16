"""로컬 Tesseract를 호출해 이미지에서 텍스트와 신뢰도를 얻는다."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from PIL import Image, ImageOps

from app.documents.extraction_models import TesseractEnvironment


class OCRError(RuntimeError):
    """OCR 엔진 실행에 실패했을 때 발생한다."""


class OCRUnavailableError(OCRError):
    pass


class OCRLanguageMissingError(OCRError):
    pass


class OCRTimeoutError(OCRError):
    pass


@dataclass(frozen=True, slots=True)
class OCRTextResult:
    text: str
    confidence: float | None
    elapsed_seconds: float
    word_count: int
    warnings: tuple[str, ...] = ()


class OCRProvider(Protocol):
    language: str
    config: str

    def recognize(self, image: Image.Image) -> OCRTextResult:
        ...


def inspect_tesseract_environment(
    required_languages: tuple[str, ...] = ("kor", "eng"),
) -> TesseractEnvironment:
    executable = shutil.which("tesseract")
    if executable is None:
        return TesseractEnvironment(
            available=False,
            executable=None,
            required_languages=list(required_languages),
            missing_languages=list(required_languages),
            error="tesseract 실행 파일을 찾지 못했습니다.",
        )

    try:
        import pytesseract

        version = str(pytesseract.get_tesseract_version())
        languages = sorted(pytesseract.get_languages(config=""))
    except Exception as error:
        return TesseractEnvironment(
            available=False,
            executable=executable,
            required_languages=list(required_languages),
            missing_languages=list(required_languages),
            error=str(error),
        )

    missing = [item for item in required_languages if item not in languages]
    return TesseractEnvironment(
        available=not missing,
        version=version,
        executable=executable,
        installed_languages=languages,
        required_languages=list(required_languages),
        missing_languages=missing,
        error=(
            None
            if not missing
            else "필수 Tesseract 언어 데이터가 없습니다: " + ", ".join(missing)
        ),
    )


class TesseractOCRProvider:
    def __init__(
        self,
        *,
        language: str = "kor+eng",
        psm: int = 4,
        oem: int = 1,
        timeout_seconds: float = 90.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds는 0보다 커야 합니다.")
        self.language = language
        self.config = f"--oem {oem} --psm {psm}"
        self.timeout_seconds = timeout_seconds

    def ensure_available(self) -> TesseractEnvironment:
        required = tuple(
            item.strip()
            for item in self.language.split("+")
            if item.strip()
        )
        environment = inspect_tesseract_environment(required)
        if environment.executable is None:
            raise OCRUnavailableError(environment.error or "Tesseract가 없습니다.")
        if environment.missing_languages:
            raise OCRLanguageMissingError(environment.error or "언어 데이터가 없습니다.")
        if not environment.available:
            raise OCRUnavailableError(environment.error or "Tesseract를 실행할 수 없습니다.")
        return environment

    @staticmethod
    def _lines_from_data(data: dict[str, list[object]]) -> tuple[str, list[float]]:
        grouped: dict[tuple[int, int, int, int], list[str]] = {}
        confidences: list[float] = []
        length = len(data.get("text", []))

        for index in range(length):
            text = str(data["text"][index]).strip()
            if not text:
                continue

            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError, KeyError, IndexError):
                confidence = -1.0

            key = (
                int(data.get("page_num", [1] * length)[index]),
                int(data.get("block_num", [0] * length)[index]),
                int(data.get("par_num", [0] * length)[index]),
                int(data.get("line_num", [0] * length)[index]),
            )
            grouped.setdefault(key, []).append(text)
            if confidence >= 0:
                confidences.append(confidence)

        lines = [" ".join(words) for _, words in sorted(grouped.items())]
        return "\n".join(lines).strip(), confidences

    def recognize(self, image: Image.Image) -> OCRTextResult:
        self.ensure_available()

        try:
            import pytesseract
            from pytesseract import Output
        except Exception as error:
            raise OCRUnavailableError(
                "pytesseract를 불러오지 못했습니다."
            ) from error

        rgb_image = image.convert("RGB")
        started = perf_counter()
        try:
            data = pytesseract.image_to_data(
                rgb_image,
                lang=self.language,
                config=self.config,
                output_type=Output.DICT,
                timeout=self.timeout_seconds,
            )
        except RuntimeError as error:
            if "timeout" in str(error).lower():
                raise OCRTimeoutError(
                    f"Tesseract OCR이 {self.timeout_seconds:.1f}초 안에 끝나지 않았습니다."
                ) from error
            raise OCRError(f"Tesseract OCR 실행에 실패했습니다: {error}") from error
        except Exception as error:
            raise OCRError(f"Tesseract OCR 실행에 실패했습니다: {error}") from error

        elapsed = perf_counter() - started
        text, confidences = self._lines_from_data(data)
        confidence = (
            sum(confidences) / len(confidences)
            if confidences
            else None
        )
        warnings: list[str] = []
        if not text:
            warnings.append("OCR 결과 텍스트가 비어 있습니다.")
        if confidence is None:
            warnings.append("유효한 OCR 신뢰도 값을 계산하지 못했습니다.")

        return OCRTextResult(
            text=text,
            confidence=confidence,
            elapsed_seconds=elapsed,
            word_count=len(confidences),
            warnings=tuple(warnings),
        )


class AdaptiveTesseractOCRProvider:
    """문서 전체 OCR 뒤 필요한 양식 영역만 로컬 보조 OCR로 보완한다.

    기본 문서 OCR은 PSM 4를 사용한다.
    전체 결과가 짧으면 PSM 11을 전체 페이지에 추가 적용한다.
    계약서는 하단 당사자 표를 별도로 읽고, 등기부의 마지막 권리 페이지는
    PSM 11 결과를 병합한다.
    """

    def __init__(
        self,
        *,
        language: str = "kor+eng",
        primary_psm: int = 4,
        fallback_psm: int = 11,
        fallback_below_characters: int = 600,
        lease_party_crop_ratio: float = 0.35,
        oem: int = 1,
        timeout_seconds: float = 60.0,
    ) -> None:
        if fallback_below_characters <= 0:
            raise ValueError("fallback_below_characters는 1 이상이어야 합니다.")
        if not 0.15 <= lease_party_crop_ratio <= 0.50:
            raise ValueError("lease_party_crop_ratio는 0.15 이상 0.50 이하여야 합니다.")
        self.language = language
        self.primary = TesseractOCRProvider(
            language=language,
            psm=primary_psm,
            oem=oem,
            timeout_seconds=timeout_seconds,
        )
        self.fallback = TesseractOCRProvider(
            language=language,
            psm=fallback_psm,
            oem=oem,
            timeout_seconds=timeout_seconds,
        )
        self.table = TesseractOCRProvider(
            language=language,
            psm=6,
            oem=oem,
            timeout_seconds=timeout_seconds,
        )
        self.config = (
            f"{self.primary.config}; fallback={self.fallback.config}; "
            f"table={self.table.config}; "
            f"threshold={fallback_below_characters}; "
            f"lease_party_crop_ratio={lease_party_crop_ratio:.2f}"
        )
        self.fallback_below_characters = fallback_below_characters
        self.lease_party_crop_ratio = lease_party_crop_ratio

    def ensure_available(self) -> TesseractEnvironment:
        return self.primary.ensure_available()

    @staticmethod
    def _compact_length(text: str) -> int:
        return len("".join(text.split()))

    @staticmethod
    def _compact_text(text: str) -> str:
        return re.sub(r"[^0-9a-z가-힣]", "", (text or "").lower())

    @classmethod
    def _looks_like_lease_contract(cls, text: str) -> bool:
        compact = cls._compact_text(text)
        return (
            "전세계약서" in compact
            or "임대차계약서" in compact
            or (
                "임대차계약" in compact
                and "보증금" in compact
                and "특약" in compact
            )
        )

    @classmethod
    def _needs_registry_sparse_pass(cls, text: str) -> bool:
        compact = cls._compact_text(text)
        registry_like = (
            "등기사항전부증명서" in compact
            or "집합건물" in compact
            or "소유권이전" in compact
        )
        final_rights_page = (
            "기록사항없음" in compact
            or "소유권이전" in compact
            or "권리자및기타사항" in compact
        )
        return registry_like and final_rights_page

    @staticmethod
    def _merge_text(primary: str, fallback: str) -> str:
        lines: list[str] = []
        seen: set[str] = set()
        for source in (primary, fallback):
            for raw in source.splitlines():
                line = " ".join(raw.split()).strip()
                key = re.sub(r"[^0-9a-z가-힣]", "", line.lower())
                if not line or not key or key in seen:
                    continue
                seen.add(key)
                lines.append(line)
        return "\n".join(lines).strip()

    @staticmethod
    def _combine_results(
        results: list[OCRTextResult],
        *,
        extra_warnings: list[str],
    ) -> OCRTextResult:
        merged = ""
        for result in results:
            merged = AdaptiveTesseractOCRProvider._merge_text(
                merged,
                result.text,
            )

        weighted: list[tuple[float, int]] = []
        for result in results:
            if result.confidence is not None and result.word_count > 0:
                weighted.append((result.confidence, result.word_count))
        confidence = (
            sum(value * count for value, count in weighted)
            / sum(count for _, count in weighted)
            if weighted
            else None
        )
        warnings: list[str] = []
        for result in results:
            warnings.extend(result.warnings)
        warnings.extend(extra_warnings)
        return OCRTextResult(
            text=merged,
            confidence=confidence,
            elapsed_seconds=sum(item.elapsed_seconds for item in results),
            word_count=sum(item.word_count for item in results),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _party_name_candidate(tokens: list[dict[str, object]], *, anchor_right: int, center_y: float, image_width: int) -> str | None:
        nearby: list[tuple[int, str]] = []
        max_right = anchor_right + int(image_width * 0.18)
        for token in tokens:
            text = re.sub(r"[^가-힣]", "", str(token["text"]))
            if not text or len(text) > 4:
                continue
            left = int(token["left"])
            top = int(token["top"])
            height = int(token["height"])
            token_center = top + height / 2
            if left < anchor_right - 4 or left > max_right:
                continue
            if abs(token_center - center_y) > 24:
                continue
            nearby.append((left, text))

        if not nearby:
            return None
        nearby.sort(key=lambda item: item[0])
        combined = ""
        last_left: int | None = None
        for left, text in nearby:
            if last_left is not None and left - last_left > int(image_width * 0.05):
                break
            if len(combined + text) > 4:
                break
            combined += text
            last_left = left
        return combined if 2 <= len(combined) <= 4 else None

    def _lease_party_name_lines(self, image: Image.Image) -> str:
        """표준 계약서 하단의 `성명` 셀을 좌표로 읽어 당사자 이름을 보강한다.

        특정 이름이나 주소를 알지 않고 `성명` 라벨 오른쪽의 같은 행 텍스트만
        사용한다. 첫 번째와 두 번째 성명 행을 각각 임대인·임차인으로 본다.
        """
        try:
            import pytesseract
            from pytesseract import Output
        except Exception:
            return ""

        crop_top = int(image.height * (1.0 - self.lease_party_crop_ratio))
        party_crop = image.crop((0, crop_top, image.width, image.height)).convert("RGB")
        try:
            data = pytesseract.image_to_data(
                party_crop,
                lang=self.language,
                config="--oem 1 --psm 11",
                output_type=Output.DICT,
                timeout=self.fallback.timeout_seconds,
            )
        except Exception:
            party_crop.close()
            return ""

        tokens: list[dict[str, object]] = []
        count = len(data.get("text", []))
        for index in range(count):
            text = str(data["text"][index]).strip()
            if not text:
                continue
            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError, KeyError, IndexError):
                confidence = -1.0
            if confidence < 15:
                continue
            tokens.append(
                {
                    "text": text,
                    "left": int(data["left"][index]),
                    "top": int(data["top"][index]),
                    "width": int(data["width"][index]),
                    "height": int(data["height"][index]),
                }
            )

        anchors: list[tuple[int, int, float]] = []
        for token in tokens:
            compact = re.sub(r"[^가-힣]", "", str(token["text"]))
            if compact == "성명":
                right = int(token["left"]) + int(token["width"])
                center = int(token["top"]) + int(token["height"]) / 2
                anchors.append((int(token["top"]), right, center))

        # `성`과 `명`이 분리된 OCR도 같은 행 라벨로 합친다.
        for first in tokens:
            if re.sub(r"[^가-힣]", "", str(first["text"])) != "성":
                continue
            first_center = int(first["top"]) + int(first["height"]) / 2
            for second in tokens:
                if re.sub(r"[^가-힣]", "", str(second["text"])) != "명":
                    continue
                second_center = int(second["top"]) + int(second["height"]) / 2
                gap = int(second["left"]) - (int(first["left"]) + int(first["width"]))
                if abs(first_center - second_center) <= 18 and -8 <= gap <= 50:
                    right = int(second["left"]) + int(second["width"])
                    anchors.append((min(int(first["top"]), int(second["top"])), right, (first_center + second_center) / 2))
                    break

        party_crop.close()
        unique_anchors: list[tuple[int, int, float]] = []
        for anchor in sorted(anchors):
            if any(abs(anchor[0] - existing[0]) <= 8 for existing in unique_anchors):
                continue
            unique_anchors.append(anchor)

        names: list[str] = []
        for _, right, center in unique_anchors:
            name = self._party_name_candidate(
                tokens,
                anchor_right=right,
                center_y=center,
                image_width=image.width,
            )
            if name and name not in names:
                names.append(name)
            if len(names) >= 2:
                break

        lines: list[str] = []
        if names:
            lines.append(f"임대인성명:{names[0]}")
        if len(names) >= 2:
            lines.append(f"임차인성명:{names[1]}")
        return "\n".join(lines)

    def recognize(self, image: Image.Image) -> OCRTextResult:
        primary = self.primary.recognize(image)
        results = [primary]
        extra_warnings: list[str] = []
        full_sparse_ran = False

        if self._compact_length(primary.text) < self.fallback_below_characters:
            try:
                results.append(self.fallback.recognize(image))
                full_sparse_ran = True
                extra_warnings.append(
                    "기본 OCR 결과가 짧아 PSM 11 전체 페이지 OCR을 병합했습니다."
                )
            except OCRError as error:
                extra_warnings.append(
                    f"PSM 11 전체 페이지 보조 OCR을 실행하지 못했습니다: {error}"
                )

        if self._needs_registry_sparse_pass(primary.text) and not full_sparse_ran:
            try:
                results.append(self.fallback.recognize(image))
                full_sparse_ran = True
                extra_warnings.append(
                    "등기부 권리 표의 말소·기록사항 문구 확인을 위해 PSM 11 결과를 병합했습니다."
                )
            except OCRError as error:
                extra_warnings.append(
                    f"등기부 권리 표 보조 OCR을 실행하지 못했습니다: {error}"
                )

        if self._looks_like_lease_contract(primary.text):
            crop_top = int(image.height * (1.0 - self.lease_party_crop_ratio))
            party_crop = image.crop((0, crop_top, image.width, image.height))
            enhanced_crop = None
            try:
                results.append(self.fallback.recognize(party_crop))
                extra_warnings.append(
                    "계약서 하단 임대인·임차인 표를 PSM 11로 추가 확인했습니다."
                )

                gray = ImageOps.grayscale(party_crop)
                enhanced_crop = ImageOps.autocontrast(gray).resize(
                    (max(1, gray.width * 2), max(1, gray.height * 2)),
                    Image.Resampling.LANCZOS,
                )
                results.append(self.table.recognize(enhanced_crop))
                extra_warnings.append(
                    "계약서 당사자 표를 확대·명암 보정한 PSM 6 OCR로 추가 확인했습니다."
                )

                party_name_lines = self._lease_party_name_lines(image)
                if party_name_lines:
                    results.append(
                        OCRTextResult(
                            text=party_name_lines,
                            confidence=primary.confidence,
                            elapsed_seconds=0.0,
                            word_count=len(party_name_lines.splitlines()),
                        )
                    )
                    extra_warnings.append(
                        "계약서 하단 성명 셀을 좌표 기반으로 추가 확인했습니다."
                    )
            except OCRError as error:
                extra_warnings.append(
                    f"계약서 하단 당사자 표 보조 OCR을 실행하지 못했습니다: {error}"
                )
            finally:
                if enhanced_crop is not None:
                    enhanced_crop.close()
                party_crop.close()

        if len(results) == 1 and not extra_warnings:
            return primary
        return self._combine_results(
            results,
            extra_warnings=extra_warnings,
        )

