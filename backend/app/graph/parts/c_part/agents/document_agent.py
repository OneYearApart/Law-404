"""
【DocumentAgent】내용증명 생성 에이전트 (Issue #22)

【무상태 설계】
  ⚠️ 지금은 conversations repository가 미완성입니다.
     그래서 대화 상태를 백엔드가 들고 있지 않습니다.

     대신 프론트가 collected(지금까지 모은 정보)를 들고 다니며
     매 요청마다 함께 보냅니다.

     conversations가 완성되면:
       - collected를 DB에 저장
       - 프론트는 conversation_id만 보내면 됨
     → 인터페이스는 그대로 두고 저장 위치만 바꾸면 됩니다.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from langchain_core.language_models import BaseLanguageModel

from app.rag.ingestion.clova_ocr import ClovaOCR

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════════════════
# 【필드 정의】내용증명에 필요한 정보
# ════════════════════════════════════════════════════════════════════════════════


REQUIRED_FIELDS = {
    "tenant_name": "임차인(본인) 성함",
    "landlord_name": "임대인(집주인) 성함",
    "landlord_address": "임대인 주소 (내용증명을 보낼 주소)",
    "property_address": "임차한 주택의 주소",
    "lease_end": "임대차 계약 종료일 (예: 2026-03-31)",
    "deposit": "보증금 액수",
}

OPTIONAL_FIELDS = {
    "tenant_address": "임차인 주소",
    "tenant_phone": "임차인 연락처",
    "contract_date": "계약 체결일",
    "lease_start": "임대차 시작일",
    "bank_account": "보증금을 받을 계좌 (은행/계좌번호/예금주)",
    "payment_deadline_days": "반환 기한 (내용증명 수령 후 며칠)",
}

# 【기본값】사용자가 안 정하면 이걸 씁니다
DEFAULT_DEADLINE_DAYS = 14  # 통상 14일. 너무 짧으면 임대인이 준비를 못 합니다.


# ════════════════════════════════════════════════════════════════════════════════
# 【프롬프트 1】정보 추출
# ════════════════════════════════════════════════════════════════════════════════

EXTRACT_PROMPT = """당신은 내용증명 작성을 돕는 어시스턴트입니다.
사용자의 메시지에서 정보를 추출하세요.

【추출할 항목】
tenant_name          임차인(본인) 성명
tenant_address       임차인 주소
tenant_phone         임차인 연락처
landlord_name        임대인(집주인) 성명
landlord_address     임대인 주소
property_address     임차한 주택의 주소
contract_date        계약 체결일 (YYYY-MM-DD)
lease_start          임대차 시작일 (YYYY-MM-DD)
lease_end            임대차 종료일 (YYYY-MM-DD)
deposit              보증금 (숫자만, 원 단위. "5천만원" → 50000000)
bank_account         입금받을 계좌
payment_deadline_days 반환 기한 (숫자, 일 단위)

【이미 알고 있는 정보】
{known_info}

【직전 질문 맥락 - 중요】
방금 사용자에게 다음 항목을 물어봤습니다: {expected_field}
→ 사용자의 새 메시지가 날짜, 숫자, 짧은 단어처럼 "그 질문에 대한 답"으로
   보이면, 반드시 이 항목({expected_field})으로 해석해서 넣으세요.
→ 예: 방금 "lease_end(임대차 종료일)"를 물었는데 사용자가 "2026-05-12"
   또는 "5월 12일"이라고만 답하면 → {{"lease_end": "2026-05-12"}}
→ 단, 사용자가 명백히 다른 항목을 말하면(예: "아 집주인 이름은 김철수요")
   그건 그대로 해당 항목에 넣으세요.
(이 값이 "(없음)"이면 직전 질문이 없는 것이니 평소대로 판단하세요.)
【사용자의 새 메시지】

{user_message}

【출력 규칙 - 엄수】
- JSON만 출력하세요. 설명, 마크다운, 백틱 금지.
- 새 메시지에서 "새로 알게 된 항목"만 넣으세요.
- 확실하지 않으면 넣지 마세요. 추측 금지.
- 이미 아는 정보를 사용자가 수정하면, 그 항목을 새 값으로 넣으세요.
- 아무것도 추출 못 하면 빈 객체 {{}}를 출력하세요.

【날짜 처리】
- "2026년 3월 31일" → "2026-03-31"
- "작년 3월" 처럼 애매하면 넣지 마세요.

【금액 처리】
- "5천만원" → 50000000
- "1억 2천" → 120000000
- 애매하면 넣지 마세요.

【출력 예시】
{{"landlord_name": "김철수", "deposit": 50000000}}
"""


# ════════════════════════════════════════════════════════════════════════════════
# 【프롬프트 2】되묻기
# ════════════════════════════════════════════════════════════════════════════════
# ⚠️ 한 번에 하나씩만 물어봅니다.
#    "이름, 주소, 계약일, 보증금 알려주세요"라고 하면
#    사용자가 일부만 답하고 나머지를 빠뜨립니다.

ASK_PROMPT = """당신은 내용증명 작성을 돕는 어시스턴트입니다.
사용자에게 부족한 정보 하나를 물어보세요.

【지금까지 모은 정보】
{known_info}

【아직 필요한 정보】
{missing_list}

【다음에 물어볼 항목】
{next_field}

【작성 요구사항】
- 위 '다음에 물어볼 항목' 하나만 물어보세요. 여러 개를 한 번에 묻지 마세요.
- 왜 필요한지 짧게 설명하세요. (사용자가 개인정보를 왜 주는지 알아야 합니다)
- 친절하되 간결하게. 2~3문장.
- 진행 상황을 알려주세요. (예: "거의 다 됐습니다")

【형식】
- 마크다운(**, ##) 사용 금지
- 일반 문장으로만

【예시】
임대인(집주인)의 주소를 알려주세요. 내용증명은 우편으로 보내야 하므로
받는 분의 주소가 정확해야 합니다. 임대차계약서에 적힌 주소를 그대로 알려주시면 됩니다.
"""


# ════════════════════════════════════════════════════════════════════════════════
# 【프롬프트 3】문서 생성
# ════════════════════════════════════════════════════════════════════════════════
# ⚠️ 여기가 핵심입니다.
#    내용증명은 법적 증거가 되므로, 표현 하나하나가 중요합니다.
#    → 형식을 엄격하게 지정하고, GPT가 창작할 여지를 줄입니다.

GENERATE_PROMPT = """당신은 주택임대차 전문가입니다.
아래 정보로 '보증금 반환 청구 내용증명'을 작성하세요.

【수집된 정보】
{collected_info}

【참고 - 법적 근거】
- 주택임대차보호법 제3조의2 (보증금의 회수)
- 민법 제536조 (동시이행의 항변권)
  → 임대인의 보증금 반환 의무와 임차인의 주택 인도 의무는 동시이행 관계입니다.
  → 임대인이 "집을 먼저 비워야 돌려준다"고 주장할 수 없습니다.

【작성할 문서 구조 - 이 형식을 정확히 따르세요】

내 용 증 명

제목: 임대차보증금 반환 청구의 건

수신인
성명: (임대인 성명)
주소: (임대인 주소)

발신인
성명: (임차인 성명)
주소: (임차인 주소, 없으면 이 줄 생략)
연락처: (연락처, 없으면 이 줄 생략)

부동산의 표시
(임차 주택 주소)

1. 귀하의 무궁한 발전을 기원합니다.

2. 발신인은 수신인과 위 부동산에 대하여 임대차계약을 체결하고
   보증금 (금액)원을 지급하였으며, 임대차 기간은 (기간)입니다.

3. 위 임대차계약은 (종료일)자로 기간이 만료되었으므로,
   수신인은 발신인에게 임대차보증금 (금액)원을 반환할 의무가 있습니다.
   (주택임대차보호법 제3조의2)

4. 이에 발신인은 수신인에게 본 내용증명 수령일로부터 (기한)일 이내에
   임대차보증금 (금액)원 전액을 반환하여 주실 것을 요청드립니다.
   (계좌가 있으면: 입금 계좌 명시)

5. 참고로 임대인의 보증금 반환 의무와 임차인의 주택 인도 의무는
   민법 제536조에 따른 동시이행 관계에 있습니다.
   따라서 발신인은 보증금 반환과 동시에 위 부동산을 인도할 준비가 되어 있습니다.

6. 만약 위 기한 내에 보증금이 반환되지 않을 경우,
   발신인은 부득이하게 임차권등기명령 신청 및 보증금반환청구소송 등
   법적 절차를 진행할 수밖에 없음을 알려드립니다.
   이 경우 발생하는 소송비용과 지연손해금은 수신인이 부담하게 됩니다.

7. 원만한 해결을 희망하며, 빠른 조치를 부탁드립니다.

(작성일)

발신인 (임차인 성명) (인)

【⚠️ 절대 규칙】
- 위 정보에 없는 내용을 지어내지 마세요.
- 정보가 없는 항목은 그 줄을 생략하세요. (예: 연락처가 없으면 연락처 줄 삭제)
- 과격한 표현("고소하겠다", "가만두지 않겠다") 금지.
  → 감정적 표현은 오히려 상대방의 법적 대응을 부릅니다.
- 마크다운(**, ##, ---) 사용 금지. 순수 텍스트로만.
- 금액은 "50,000,000원" 형식으로 쉼표를 넣으세요.
- 날짜는 모두 "2026년 3월 31일" 형식으로 통일하세요. 
- YYYY-MM-DD 형식(2026-03-31)을 본문에 쓰지 마세요.
"""


# ════════════════════════════════════════════════════════════════════════════════
# 【DocumentAgent】
# ════════════════════════════════════════════════════════════════════════════════


class DocumentAgent:
    def __init__(self, llm: BaseLanguageModel, ocr: Optional[ClovaOCR] = None):
        self.llm = llm
        # 【OCR】없으면 자동 생성. URL/Secret 미설정이면 is_available()=False
        self.ocr = ocr or ClovaOCR()

    # ────────────────────────────────────────────────────────────────────────
    # 【1】정보 추출
    # ────────────────────────────────────────────────────────────────────────

    async def extract_info(
        self,
        user_message: str,
        collected: dict,
        expected_field: Optional[str] = None,
    ) -> dict:

        logger.info(f"[DocumentAgent] 정보 추출: '{user_message[:40]}...'")

        # 【이미 아는 정보를 프롬프트에 넣기】
        # → GPT가 중복 추출하거나, 수정 요청을 알아채도록
        known = self._format_known_info(collected)

        # expected_field(라벨 포함)를 사람이 읽는 형태로
        expected_label = "(없음)"
        if expected_field:
            label = REQUIRED_FIELDS.get(expected_field) or OPTIONAL_FIELDS.get(
                expected_field, ""
            )
            expected_label = f"{expected_field} ({label})" if label else expected_field

        prompt = EXTRACT_PROMPT.format(
            known_info=known or "(없음)",
            expected_field=expected_label,
            user_message=user_message,
        )

        response = await self.llm.ainvoke(prompt)
        content = response.content.strip()

        # 【JSON 파싱】
        # ⚠️ GPT가 ```json ... ``` 로 감쌀 수 있습니다. 제거합니다.
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        try:
            extracted = json.loads(content)
        except json.JSONDecodeError:
            logger.warning(f"[DocumentAgent] JSON 파싱 실패: {content[:100]}")
            return collected  # 추출 실패 → 기존 정보 유지

        if not isinstance(extracted, dict):
            return collected

        # 【병합】새로 추출한 것만 덮어씀
        updated = dict(collected)

        for key, value in extracted.items():
            # 알 수 없는 필드는 무시 (GPT가 이상한 키를 만들 수 있음)
            if key not in REQUIRED_FIELDS and key not in OPTIONAL_FIELDS:
                continue

            # None이나 빈 값은 무시
            if value is None or value == "":
                continue

            updated[key] = value
            logger.info(f"[DocumentAgent]   → {key} = {value}")

        # 내부 관리용 키는 collected에 남기지 않는다(다음 턴에 process가 다시 설정).
        updated.pop("_awaiting", None)

        return updated

    # ────────────────────────────────────────────────────────────────────────
    # 【OCR】이미지에서 정보 추출
    # ────────────────────────────────────────────────────────────────────────

    async def extract_from_image(
        self,
        image_base64: str,
        image_format: str,
        collected: dict,
    ) -> dict:
        """
        【OCR 추출】계약서 이미지 → 텍스트 → 정보 추출

        ⚠️ 이게 OCR의 핵심 가치입니다.
           사용자가 6개 항목을 타이핑하는 대신,
           계약서 한 장을 찍으면 대부분 자동으로 채워집니다.

        흐름:
          1. 클로바 OCR로 이미지 → 텍스트
          2. 그 텍스트를 extract_info()로 넘김 (기존 메서드 재사용!)
          3. collected 자동 채움

        Args:
            image_base64: base64 인코딩된 이미지
            image_format: "jpg", "png", "pdf"
            collected: 지금까지 모은 정보

        Returns:
            업데이트된 collected

        Raises:
            RuntimeError: OCR 미설정 또는 처리 실패

        ⚠️ 개인정보 주의:
           계약서에는 민감정보가 많습니다.
           OCR 텍스트를 로그에 남기지 않습니다.
        """
        # 【OCR 사용 가능 확인】
        if not self.ocr.is_available():
            raise RuntimeError(
                "OCR이 설정되지 않았습니다. 텍스트로 정보를 직접 입력해 주세요."
            )

        logger.info("[DocumentAgent] 이미지에서 정보 추출 시작")

        # 【1】OCR로 텍스트 추출
        # ⚠️ 추출된 텍스트는 개인정보를 포함하므로 로그에 남기지 않습니다.
        try:
            ocr_text = self.ocr.extract_text_from_base64(
                image_base64,
                image_format,
            )
        except Exception as e:
            logger.error(f"[DocumentAgent] OCR 실패: {type(e).__name__}")
            raise RuntimeError(
                "이미지에서 텍스트를 읽지 못했습니다. "
                "더 선명한 사진으로 다시 시도하거나, "
                "텍스트로 입력해 주세요."
            )

        if not ocr_text.strip():
            raise RuntimeError(
                "이미지에서 텍스트를 찾지 못했습니다. "
                "계약서가 잘 보이는 사진인지 확인해 주세요."
            )

        logger.info(f"[DocumentAgent] OCR 완료 ({len(ocr_text)}자 추출)")

        # 【2】추출된 텍스트를 기존 extract_info()로 넘김
        # ⚠️ 여기가 핵심! OCR 텍스트든 사용자 타이핑이든
        #    똑같이 extract_info()로 처리합니다. 코드 재사용.
        updated = await self.extract_info(
            user_message=ocr_text,
            collected=collected,
        )

        return updated

    async def process_image(
        self,
        image_base64: str,
        image_format: str,
        collected: Optional[dict] = None,
    ) -> dict:
        """
        【OCR 통합 처리】이미지 → 정보 추출 → 다음 행동 판단

        process()의 이미지 버전입니다.

        흐름:
          1. 이미지에서 정보 추출 (OCR)
          2. 아직 부족한 정보가 있나?
          3-A. 부족 → 되묻기
          3-B. 충분 → 문서 생성

        Returns:
            process()와 동일한 형식
            {
              "status": "need_more_info" | "complete",
              "collected": {...},
              "extracted_from_image": [...],  # ← 이미지에서 새로 찾은 항목
              ...
            }
        """
        collected = collected or {}
        before = set(collected.keys())

        # 【1】이미지에서 정보 추출
        collected = await self.extract_from_image(
            image_base64=image_base64,
            image_format=image_format,
            collected=collected,
        )

        # 【이미지에서 새로 찾은 항목】사용자에게 알려주기 위해
        after = set(collected.keys())
        newly_found = after - before

        # 【2】부족한 게 있나?
        missing = self.get_missing_fields(collected)

        total = len(REQUIRED_FIELDS)
        filled = total - len(missing)
        progress = filled / total

        # 【3-A】부족 → 되묻기
        if missing:
            question = await self.ask_next(collected, missing)

            # ★ 이번에 물어보는 항목을 기록 → 다음 턴 extract_info의 힌트로 사용
            collected = dict(collected)
            collected["_awaiting"] = missing[0]

            logger.info(
                f"[DocumentAgent] 이미지에서 {len(newly_found)}개 추출, "
                f"{len(missing)}개 부족"
            )

            return {
                "status": "need_more_info",
                "collected": collected,
                "extracted_from_image": [
                    REQUIRED_FIELDS[f] for f in newly_found if f in REQUIRED_FIELDS
                ],
                "missing": missing,
                "missing_labels": [REQUIRED_FIELDS[f] for f in missing],
                "progress": round(progress, 2),
                "next_question": question,
                "document": None,
            }

        # 【3-B】충분 → 문서 생성
        logger.info("[DocumentAgent] 이미지만으로 정보 완성 → 문서 생성")

        document = await self.generate_document(collected)

        return {
            "status": "complete",
            "collected": collected,
            "extracted_from_image": [
                REQUIRED_FIELDS[f] for f in newly_found if f in REQUIRED_FIELDS
            ],
            "missing": [],
            "missing_labels": [],
            "progress": 1.0,
            "next_question": None,
            "document": document,
        }

    # ────────────────────────────────────────────────────────────────────────
    # 【2】부족한 정보 확인
    # ────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_missing_fields(collected: dict) -> list[str]:
        """
        【확인】아직 없는 필수 항목

        ⚠️ 필수(REQUIRED_FIELDS)만 봅니다.
           선택 항목까지 다 물어보면 사용자가 지칩니다.
        """
        return [field for field in REQUIRED_FIELDS if not collected.get(field)]

    # ────────────────────────────────────────────────────────────────────────
    # 【3】되묻기
    # ────────────────────────────────────────────────────────────────────────

    async def ask_next(
        self,
        collected: dict,
        missing: list[str],
    ) -> str:
        """
        【되묻기】부족한 정보 하나를 물어보는 질문 생성

        ⚠️ 한 번에 하나씩만 물어봅니다.
           여러 개를 묻으면 사용자가 일부만 답하고 나머지를 빠뜨립니다.

        ⚠️ 순서가 중요합니다.
           REQUIRED_FIELDS의 정의 순서대로 물어봅니다.
           (이름 → 상대방 → 주소 → 계약 → 금액)
           자연스러운 대화 흐름입니다.
        """
        if not missing:
            return ""

        next_field = missing[0]
        next_label = REQUIRED_FIELDS[next_field]

        logger.info(f"[DocumentAgent] 되묻기: {next_field}")

        prompt = ASK_PROMPT.format(
            known_info=self._format_known_info(collected) or "(아직 없음)",
            missing_list="\n".join(f"- {REQUIRED_FIELDS[f]}" for f in missing),
            next_field=f"{next_field} ({next_label})",
        )

        response = await self.llm.ainvoke(prompt)
        return response.content.strip()

    # ────────────────────────────────────────────────────────────────────────
    # 【4】문서 생성
    # ────────────────────────────────────────────────────────────────────────

    async def generate_document(self, collected: dict) -> str:
        """
        【생성】내용증명 본문

        ⚠️ 필수 정보가 다 있어야 호출하세요.
           없으면 GPT가 빈칸을 지어냅니다.
        """
        logger.info("[DocumentAgent] 문서 생성")

        # 【기본값 채우기】
        # 반환 기한을 사용자가 안 정했으면 14일로
        info = dict(collected)
        if not info.get("payment_deadline_days"):
            info["payment_deadline_days"] = DEFAULT_DEADLINE_DAYS

        # 작성일 = 오늘
        info["writing_date"] = datetime.now().strftime("%Y년 %m월 %d일")

        prompt = GENERATE_PROMPT.format(
            collected_info=self._format_known_info(info, verbose=True),
        )

        response = await self.llm.ainvoke(prompt)
        document = response.content.strip()

        # 【검증】GPT가 마크다운을 남겼으면 제거
        document = re.sub(r"\*\*", "", document)  # 볼드
        document = re.sub(r"^#+\s*", "", document, flags=re.MULTILINE)  # 헤더
        document = re.sub(r" +\n", "\n", document)
        document = re.sub(r"\n{3,}", "\n\n", document)

        return document.strip()

    # ────────────────────────────────────────────────────────────────────────
    # 【5】process — 에이전트의 핵심
    # ────────────────────────────────────────────────────────────────────────

    async def process(
        self,
        user_message: str,
        collected: Optional[dict] = None,
    ) -> dict:
        """
        【메인】사용자 메시지를 처리하고 다음 행동을 결정

        ⚠️ 이 메서드가 '에이전트'를 만듭니다.
           스스로 판단합니다:
             정보가 부족한가? → 되묻는다
             정보가 충분한가? → 문서를 만든다

           AnswerGenerator는 이런 판단을 하지 않습니다.
           무조건 7개 섹션을 만들고 끝냅니다.

        Args:
            user_message: 사용자 메시지
            collected: 지금까지 모은 정보 (프론트가 들고 있던 것)

        Returns:
            {
              "status": "need_more_info" | "complete",
              "collected": {...},          # 업데이트된 정보 (프론트가 다시 들고 있어야 함)
              "missing": [...],            # 아직 없는 항목
              "progress": 0.67,            # 진행률 (프론트 UI용)
              "next_question": "...",      # status=need_more_info일 때
              "document": "...",           # status=complete일 때
            }
        """
        collected = collected or {}

        # 【1】사용자 메시지에서 정보 추출
        # ⚠️ 첫 요청("내용증명 써줘")에는 정보가 없을 수 있습니다.
        #    그래도 호출합니다. 혹시 정보가 섞여 있을 수 있으니까요.
        #    ("내용증명 써줘, 집주인은 김철수야" 같은 경우)
        collected = await self.extract_info(user_message, collected)

        # 【2】아직 부족한 게 있나?
        missing = self.get_missing_fields(collected)

        # 【진행률】프론트에서 진행바를 그릴 수 있게
        total = len(REQUIRED_FIELDS)
        filled = total - len(missing)
        progress = filled / total

        # 【3-A】부족하면 → 되묻는다
        if missing:
            question = await self.ask_next(collected, missing)

            # ★ 이번에 물어보는 항목을 기록 → 다음 턴 extract_info의 힌트로 사용
            collected = dict(collected)
            collected["_awaiting"] = missing[0]

            logger.info(
                f"[DocumentAgent] 정보 부족 "
                f"({filled}/{total}) — 다음 질문: {missing[0]}"
            )

            return {
                "status": "need_more_info",
                "collected": collected,
                "missing": missing,
                "missing_labels": [REQUIRED_FIELDS[f] for f in missing],
                "progress": round(progress, 2),
                "next_question": question,
                "document": None,
            }

        # 【3-B】다 모였으면 → 문서를 만든다
        logger.info(f"[DocumentAgent] 정보 수집 완료 → 문서 생성")

        document = await self.generate_document(collected)

        return {
            "status": "complete",
            "collected": collected,
            "missing": [],
            "missing_labels": [],
            "progress": 1.0,
            "next_question": None,
            "document": document,
        }

    # ────────────────────────────────────────────────────────────────────────
    # 【헬퍼】
    # ────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_known_info(collected: dict, verbose: bool = False) -> str:
        """
        【포맷팅】수집된 정보를 프롬프트용 텍스트로

        Args:
            verbose: True면 없는 항목도 "(미입력)"으로 표시
                     (문서 생성 시 GPT가 뭐가 없는지 알아야 하므로)
        """
        if not collected and not verbose:
            return ""

        lines = []
        all_fields = {**REQUIRED_FIELDS, **OPTIONAL_FIELDS}

        for key, label in all_fields.items():
            value = collected.get(key)

            if value:
                # 【금액은 읽기 좋게】
                if key == "deposit" and isinstance(value, int):
                    lines.append(f"{key} ({label}): {value:,}원")
                else:
                    lines.append(f"{key} ({label}): {value}")

            elif verbose:
                lines.append(f"{key} ({label}): (미입력)")

        # 【작성일】문서 생성 시에만
        if verbose and collected.get("writing_date"):
            lines.append(f"writing_date (작성일): {collected['writing_date']}")

        return "\n".join(lines)
