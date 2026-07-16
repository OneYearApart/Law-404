

import base64
import json
import logging
import time
import uuid
from typing import Optional

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)


class ClovaOCR:


    def __init__(
        self,
        invoke_url: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        """
        Args:
            invoke_url: APIGW Invoke URL. 없으면 settings에서 가져옴.
            secret_key: X-OCR-SECRET. 없으면 settings에서 가져옴.
        """
        # ⚠️ config.py에 CLOVA_OCR_URL, CLOVA_OCR_SECRET을 추가해야 합니다.
        #    getattr로 감싸서, 필드가 없어도 에러 없이 빈 문자열이 되게 합니다.
        self.invoke_url = invoke_url or getattr(settings, "CLOVA_OCR_URL", "")
        self.secret_key = secret_key or getattr(settings, "CLOVA_OCR_SECRET", "")

    def is_available(self) -> bool:

        return bool(self.invoke_url and self.secret_key)

    # ────────────────────────────────────────────────────────────────────────
    # 【핵심】이미지 bytes → 텍스트
    # ────────────────────────────────────────────────────────────────────────

    def extract_text_from_bytes(
        self,
        image_bytes: bytes,
        image_format: str = "jpg",
    ) -> str:

        if not self.is_available():
            raise RuntimeError(
                "클로바 OCR이 설정되지 않았습니다. "
                ".env에 CLOVA_OCR_URL과 CLOVA_OCR_SECRET을 넣어주세요."
            )

        # 【요청 본문 구성】
        # 클로바 OCR General API 형식:
        # https://api.ncloud-docs.com/docs/ai-application-service-ocr-general
        request_json = {
            "version": "V2",
            "requestId": str(uuid.uuid4()),   # 매 요청 고유 ID
            "timestamp": int(time.time() * 1000),
            "images": [
                {
                    "format": image_format,
                    "name": "document",       # 임의 이름 (개인정보 아님)
                    "data": base64.b64encode(image_bytes).decode("utf-8"),
                }
            ],
        }

        headers = {
            "Content-Type": "application/json",
            # ⚠️ Secret Key는 헤더로만 전송. 로그에 남기지 않음.
            "X-OCR-SECRET": self.secret_key,
        }

        # 【API 호출】
        logger.info("[ClovaOCR] 텍스트 추출 요청")
        # ⚠️ 이미지 데이터나 결과는 로그에 남기지 않습니다 (개인정보).

        try:
            response = requests.post(
                self.invoke_url,
                headers=headers,
                data=json.dumps(request_json).encode("utf-8"),
                timeout=30,
            )
            response.raise_for_status()

        except requests.exceptions.Timeout:
            logger.error("[ClovaOCR] 타임아웃")
            raise RuntimeError("OCR 처리 시간이 초과되었습니다. 다시 시도해 주세요.")

        except requests.exceptions.RequestException as e:
            # 【디버깅】응답 본문을 출력 (원인 파악용)
            status = getattr(e.response, 'status_code', '?')
            body = getattr(e.response, 'text', '')
            logger.error(f"[ClovaOCR] API 오류 {status}: {body}")
            raise RuntimeError(f"OCR 오류 {status}: {body}")

        # 【응답 파싱】
        result = response.json()
        return self._parse_result(result)

    def extract_text_from_base64(
        self,
        base64_str: str,
        image_format: str = "jpg",
    ) -> str:

        if "," in base64_str and base64_str.startswith("data:"):
            base64_str = base64_str.split(",", 1)[1]

        image_bytes = base64.b64decode(base64_str)
        return self.extract_text_from_bytes(image_bytes, image_format)

    # ────────────────────────────────────────────────────────────────────────
    # 【파싱】OCR 응답 → 텍스트
    # ────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_result(result: dict) -> str:

        try:
            images = result.get("images", [])
            if not images:
                return ""

            fields = images[0].get("fields", [])
            if not fields:
                return ""

            parts = []
            for field in fields:
                text = field.get("inferText", "")
                parts.append(text)


                if field.get("lineBreak", False):
                    parts.append("\n")
                else:
                    parts.append(" ")

            text = "".join(parts)

            lines = [line.strip() for line in text.split("\n")]
            text = "\n".join(line for line in lines if line)

            return text

        except (KeyError, IndexError, TypeError) as e:
            logger.error(f"[ClovaOCR] 응답 파싱 실패: {e}")
            return ""


# ════════════════════════════════════════════════════════════════════════════════
# 【테스트】직접 실행
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":

    import sys

    logging.basicConfig(level=logging.INFO)

    ocr = ClovaOCR()

    print("=" * 60)
    print("클로바 OCR 테스트")
    print("=" * 60)

    # 【1】설정 확인
    if not ocr.is_available():
        print("❌ OCR 미설정")
        print("   .env에 CLOVA_OCR_URL, CLOVA_OCR_SECRET을 넣으세요.")
        sys.exit(1)

    print("✅ OCR 설정 확인됨")
    print(f"   URL: {ocr.invoke_url[:40]}...")

    # 【2】이미지 경로가 주어지면 실제 추출
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
        print(f"\n이미지: {image_path}")

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        # 확장자로 포맷 판단
        ext = image_path.rsplit(".", 1)[-1].lower()

        print("추출 중...")
        text = ocr.extract_text_from_bytes(image_bytes, ext)

        print("\n" + "=" * 60)
        print("추출 결과")
        print("=" * 60)
        print(text)
    else:
        print("\n이미지 경로를 주면 실제 추출을 테스트합니다:")
        print("  python -m app.rag.ingestion.clova_ocr 계약서.jpg")