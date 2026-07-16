"""
【CostRepository】공식 비용 데이터 조회

"""

import logging
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from app.core.config import settings

logger = logging.getLogger(__name__)


class CostRepository:
    """
    【비용 데이터 조회】

    """

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or settings.database_url

    def _connect(self):
        return psycopg2.connect(self.db_url, cursor_factory=RealDictCursor)

    # ────────────────────────────────────────────────────────────────────────
    # 【절차 비용】
    # ────────────────────────────────────────────────────────────────────────

    def get_all_procedures(self) -> list[dict]:
        """
        【조회】모든 절차의 비용 정보
        """
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT procedure_name,
                               description,
                               fixed_cost_total,
                               fixed_cost_breakdown,
                               variable_cost_formula,
                               eligibility,
                               cost_source,
                               cost_caution
                        FROM procedure_info
                        ORDER BY id
                    """)
                    rows = cur.fetchall()
                    return [dict(r) for r in rows]

        except Exception as e:
            logger.error(f"절차 비용 조회 실패: {e}")
            # ⚠️ 빈 리스트를 반환합니다. 예외를 던지지 않는 이유:
            #    DB가 죽어도 답변 생성 자체는 되어야 합니다.
            #    대신 프롬프트에서 "비용 정보 없음"으로 처리됩니다.
            return []

    def get_procedure_costs_for_prompt(self) -> str:
        """
        【포맷팅】절차 비용을 프롬프트에 넣을 텍스트로 변환
        """
        procedures = self.get_all_procedures()

        if not procedures:
            # 【DB 조회 실패 시】정직하게 "모른다"고 안내
            return (
                "⚠️ 공식 비용 데이터를 불러오지 못했습니다.\n"
                "구체적인 금액을 제시하지 말고, "
                "'대법원 전자소송(ecfs.scourt.go.kr) 또는 관할 법원에서 "
                "확인하시기 바랍니다'라고 안내하세요."
            )

        lines = []

        for p in procedures:
            name = p["procedure_name"]
            lines.append(f"\n━━━ {name} ━━━")

            # 【신청 자격】
            if p.get("eligibility"):
                lines.append(f"[신청 자격] {p['eligibility']}")

            # 【케이스 A】고정 금액이 있는 절차 (임차권등기명령)
            if p.get("fixed_cost_total"):
                total = p["fixed_cost_total"]
                lines.append(f"[총 비용] {total:,}원")

                if p.get("fixed_cost_breakdown"):
                    lines.append(f"[내역] {p['fixed_cost_breakdown']}")

            # 【케이스 B】계산 공식이 있는 절차 (소액사건, 일반소송)
            elif p.get("variable_cost_formula"):
                lines.append("[비용 계산 방법]")
                lines.append(p["variable_cost_formula"])

            # 【케이스 C】공식 데이터가 없는 절차 (내용증명, 경매배당)
            else:
                lines.append("[비용] ⚠️ 공식 금액 자료 없음 — 금액을 제시하지 마세요.")

            # 【출처】답변에 함께 표시할 것
            if p.get("cost_source"):
                lines.append(f"[출처] {p['cost_source']}")

            # 【주의사항】비용이 달라지는 경우
            if p.get("cost_caution"):
                lines.append(f"[주의] {p['cost_caution']}")

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────────────────────
    # 【지역 기준】
    # ────────────────────────────────────────────────────────────────────────

    def get_all_region_tiers(self) -> list[dict]:
        """
        【조회】지역별 소액임차인 기준 (4단계)
        """
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT tier_name,
                               tier_description,
                               deposit_threshold,
                               max_priority_payment,
                               caution_note,
                               legal_basis
                        FROM region_standards
                        ORDER BY deposit_threshold DESC
                    """)
                    rows = cur.fetchall()
                    return [dict(r) for r in rows]

        except Exception as e:
            logger.error(f"지역 기준 조회 실패: {e}")
            return []

    def get_region_standards_for_prompt(self) -> str:
        """
        【포맷팅】지역 기준을 프롬프트용 텍스트로 변환

        ⚠️ 두 금액을 명확히 구분해서 표시합니다.
           GPT가 이 둘을 혼동하는 경우가 많습니다:
           - deposit_threshold:    "소액임차인 자격 기준"
           - max_priority_payment: "실제 받는 최대 금액"

           예) 서울, 보증금 1억
               → 소액임차인 O (1.65억 이하니까)
               → 하지만 최우선변제는 5,500만원까지만!
        """
        tiers = self.get_all_region_tiers()

        if not tiers:
            return (
                "⚠️ 지역별 기준 데이터를 불러오지 못했습니다.\n"
                "구체적 금액을 제시하지 말고, 인터넷등기소(iros.go.kr)에서 "
                "확인하도록 안내하세요."
            )

        lines = [
            "【소액임차인 최우선변제 기준 - 주택임대차보호법 시행령 제11조】",
            "",
            "⚠️ 아래 두 금액은 다릅니다. 반드시 구분해서 설명하세요:",
            "  · '보증금 기준' = 이 금액 이하여야 소액임차인 자격이 생김",
            "  · '최우선변제금' = 실제로 우선 배당받는 최대 금액",
            "",
        ]

        for t in tiers:
            # 【금액을 읽기 쉽게】억/만원 단위로
            threshold_eok = t["deposit_threshold"] / 100_000_000
            payment_manwon = t["max_priority_payment"] / 10_000

            lines.append(f"━━━ {t['tier_name']} ━━━")
            lines.append(f"[적용 범위] {t['tier_description']}")
            lines.append(
                f"[보증금 기준] {t['deposit_threshold']:,}원 "
                f"({threshold_eok:.2f}억) 이하"
            )
            lines.append(
                f"[최우선변제금] 최대 {t['max_priority_payment']:,}원 "
                f"({payment_manwon:,.0f}만원)"
            )

            # 【주의사항】경기/인천처럼 애매한 경우
            if t.get("caution_note"):
                lines.append(f"[⚠️ 주의] {t['caution_note']}")

            lines.append("")

        # 【공통 제약】법령상 상한
        lines.append(
            "⚠️ 공통 제약: 최우선변제금은 주택가액(낙찰가)의 1/2을 넘을 수 없습니다."
        )
        lines.append(
            "⚠️ 기준 시점: 등기부상 '최초 담보권 설정일' 기준입니다. "
            "계약일이나 입주일이 아닙니다."
        )

        return "\n".join(lines)

    # ────────────────────────────────────────────────────────────────────────
    # 【인지대 계산】공식 기반 (GPT에게 맡기지 않고 코드로 계산)
    # ────────────────────────────────────────────────────────────────────────

    @staticmethod
    def calculate_stamp_fee(claim_amount: int) -> dict:
        """
        【계산】인지대 (민사소송 등 인지법 제2조)

        """
        if claim_amount < 10_000_000:
            fee = claim_amount * 50 / 10_000
            formula = "소가 1천만원 미만: 소가 × 50/10,000"

        elif claim_amount < 100_000_000:
            fee = claim_amount * 45 / 10_000 + 5_000
            formula = "소가 1천만원 이상 1억원 미만: 소가 × 45/10,000 + 5,000원"

        elif claim_amount < 1_000_000_000:
            fee = claim_amount * 40 / 10_000 + 55_000
            formula = "소가 1억원 이상 10억원 미만: 소가 × 40/10,000 + 55,000원"

        else:
            fee = claim_amount * 35 / 10_000 + 555_000
            formula = "소가 10억원 이상: 소가 × 35/10,000 + 555,000원"

        # 【단수 처리】법령 규정대로
        # 1) 1,000원 미만이면 1,000원
        # 2) 100원 미만 단수는 절사
        fee = int(fee)
        if fee < 1_000:
            fee = 1_000
        else:
            fee = (fee // 100) * 100

        return {
            "stamp_fee": fee,
            "formula_used": formula,
            "legal_basis": "민사소송 등 인지법 제2조",
        }

    @staticmethod
    def calculate_service_fee(case_type: str, party_count: int = 2) -> dict:
        """
        【계산】송달료 (송달료규칙 별표1)

        Args:
            case_type: "소액사건" | "일반소송"
            party_count: 당사자 수 (원고1 + 피고1 = 2가 기본)

        Returns:
            {
              "service_fee": 계산된 송달료,
              "formula_used": 계산 근거,
              "legal_basis": 근거
            }

        기준:
            1회 송달료 = 5,500원
            소액사건:  당사자수 × 10회
            일반소송:  당사자수 × 15회
        """
        UNIT_FEE = 5_500  # 1회 송달료 (국내 통상우편요금)

        rounds_map = {
            "소액사건": 10,
            "일반소송": 15,
        }

        rounds = rounds_map.get(case_type)

        if rounds is None:
            # 【모르는 사건 유형】지어내지 않고 None 반환
            return {
                "service_fee": None,
                "formula_used": f"'{case_type}'의 송달료 기준을 알 수 없습니다.",
                "legal_basis": None,
            }

        fee = party_count * UNIT_FEE * rounds

        return {
            "service_fee": fee,
            "formula_used": (
                f"{case_type}: 당사자 {party_count}명 × "
                f"1회 {UNIT_FEE:,}원 × {rounds}회분 = {fee:,}원"
            ),
            "legal_basis": "송달료규칙의 시행에 따른 업무처리요령 별표1",
        }

    def calculate_total_cost(
        self,
        claim_amount: int,
        procedure: str,
        party_count: int = 2,
    ) -> dict:
        """
        【계산】특정 절차의 총 비용

        """
        # 【1】고정 비용 절차인지 먼저 확인 (임차권등기명령)
        procedures = {p["procedure_name"]: p for p in self.get_all_procedures()}
        info = procedures.get(procedure)

        if not info:
            return {
                "procedure": procedure,
                "total": None,
                "breakdown": [f"'{procedure}'의 비용 정보가 DB에 없습니다."],
                "source": None,
                "caution": "관할 법원에 문의하세요.",
            }

        # 【케이스 A】고정 금액 (임차권등기명령)
        if info.get("fixed_cost_total"):
            return {
                "procedure": procedure,
                "total": info["fixed_cost_total"],
                "breakdown": [info["fixed_cost_breakdown"]],
                "source": info["cost_source"],
                "caution": info["cost_caution"],
            }

        # 【케이스 B】계산이 필요한 절차 (소액사건, 일반소송)
        if procedure in ("소액사건", "일반소송"):
            stamp = self.calculate_stamp_fee(claim_amount)
            service = self.calculate_service_fee(procedure, party_count)

            total = stamp["stamp_fee"] + (service["service_fee"] or 0)

            return {
                "procedure": procedure,
                "total": total,
                "breakdown": [
                    f"인지대: {stamp['stamp_fee']:,}원 ({stamp['formula_used']})",
                    f"송달료: {service['service_fee']:,}원 ({service['formula_used']})",
                ],
                "source": f"{stamp['legal_basis']} / {service['legal_basis']}",
                "caution": info.get("cost_caution"),
            }

        # 【케이스 C】공식 데이터 없음 (내용증명, 경매배당)
        return {
            "procedure": procedure,
            "total": None,
            "breakdown": ["공식 금액 자료가 없습니다."],
            "source": info.get("cost_source"),
            "caution": info.get("cost_caution"),
        }


# ════════════════════════════════════════════════════════════════════════════════
# 【테스트】직접 실행해서 확인
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    repo = CostRepository()

    print("=" * 74)
    print("【1】절차 비용 (프롬프트용 텍스트)")
    print("=" * 74)
    print(repo.get_procedure_costs_for_prompt())

    print("\n" + "=" * 74)
    print("【2】지역 기준 (프롬프트용 텍스트)")
    print("=" * 74)
    print(repo.get_region_standards_for_prompt())

    print("\n" + "=" * 74)
    print("【3】계산 테스트 - 보증금 5,000만원인 경우")
    print("=" * 74)

    for proc in ["임차권등기명령", "소액사건", "일반소송"]:
        result = repo.calculate_total_cost(50_000_000, proc)
        print(f"\n[{proc}]")
        if result["total"]:
            print(f"  총액: {result['total']:,}원")
        else:
            print(f"  총액: 산정 불가")
        for line in result["breakdown"]:
            print(f"  - {line}")