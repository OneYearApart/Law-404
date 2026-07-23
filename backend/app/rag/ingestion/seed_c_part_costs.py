"""
【시드 스크립트】공식 법령 데이터 입력
"""

from datetime import datetime

import psycopg2
from psycopg2.extras import execute_values

# 【DB 접속】
DB_URL = "postgresql://edu:1234@localhost:5433/edudb"


# ════════════════════════════════════════════════════════════════════════════════
# 【데이터 1】지역별 소액임차인 기준 (4단계)
# ════════════════════════════════════════════════════════════════════════════════

REGION_TIERS = [
    {
        "tier_name": "서울특별시",
        "tier_description": "서울특별시 전역",
        "deposit_threshold": 165_000_000,  # 1억 6,500만원
        "max_priority_payment": 55_000_000,  # 5,500만원
        "caution_note": None,  # 서울은 구분이 명확해서 주의사항 없음
        "legal_basis": "주택임대차보호법 시행령 제11조 (2023.2.21 개정)",
    },
    {
        "tier_name": "과밀억제권역 등",
        "tier_description": (
            "수도권정비계획법에 따른 과밀억제권역(서울특별시 제외), "
            "세종특별자치시, 용인시, 화성시, 김포시"
        ),
        "deposit_threshold": 145_000_000,  # 1억 4,500만원
        "max_priority_payment": 48_000_000,  # 4,800만원
        # ⚠️ 여기가 핵심 주의사항
        "caution_note": (
            "경기도·인천광역시는 시·군에 따라 등급이 다릅니다. "
            "본인 거주지가 과밀억제권역에 해당하는지 반드시 확인하세요. "
            "확인처: 인터넷등기소(iros.go.kr) > 소액임차인의 범위 등"
        ),
        "legal_basis": "주택임대차보호법 시행령 제11조 (2023.2.21 개정)",
    },
    {
        "tier_name": "광역시 등",
        "tier_description": (
            "광역시(과밀억제권역에 포함된 지역과 군지역은 제외), "
            "안산시, 광주시, 파주시, 이천시, 평택시"
        ),
        "deposit_threshold": 85_000_000,  # 8,500만원
        "max_priority_payment": 28_000_000,  # 2,800만원
        "caution_note": (
            "광역시라도 군지역(예: 부산 기장군)은 '그 밖의 지역'으로 분류됩니다."
        ),
        "legal_basis": "주택임대차보호법 시행령 제11조 (2023.2.21 개정)",
    },
    {
        "tier_name": "그 밖의 지역",
        "tier_description": "위 세 구분에 해당하지 않는 모든 지역",
        "deposit_threshold": 75_000_000,  # 7,500만원
        "max_priority_payment": 25_000_000,  # 2,500만원
        "caution_note": None,
        "legal_basis": "주택임대차보호법 시행령 제11조 (2023.2.21 개정)",
    },
]


# ════════════════════════════════════════════════════════════════════════════════
# 【데이터 2】절차별 공식 비용
# ════════════════════════════════════════════════════════════════════════════════
# ⚠️ 비용의 성격이 두 가지입니다:
#    (A) 고정 금액  → 임차권등기명령 (소가와 무관, 43,400원)
#    (B) 계산 공식  → 소액사건/일반소송 (소가에 비례)
#
#    그래서 fixed_cost_* 와 variable_cost_formula 를 나눴습니다.
#    GPT에게는 "이 값/공식만 쓰고, 없는 건 만들지 마라"고 지시할 것입니다.

PROCEDURE_COSTS = [
    # ────────────────────────────────────────────────────────────────────────
    # 【1】임차권등기명령 — 고정 금액 (가장 확실한 데이터)
    # ────────────────────────────────────────────────────────────────────────
    {
        "procedure_name": "임차권등기명령",
        "fixed_cost_total": 43_400,
        "fixed_cost_breakdown": (
            "인지세(수입인지) 2,000원 + "
            "등기수입증지 3,000원(1부동산당) + "
            "송달료 31,200원(1회 5,200원 × 6회) + "
            "등록면허세(지방교육세 포함) 7,200원"
        ),
        "variable_cost_formula": None,  # 소가와 무관
        "eligibility": (
            "임대차가 종료되었으나 보증금을 반환받지 못한 임차인. "
            "계약기간이 남아있으면 원칙적으로 신청 불가."
        ),
        "cost_source": "법제처 찾기쉬운 생활법령정보 (2026.6.15 기준)",
        "cost_caution": (
            "임대인이 여러 명이거나 부동산이 여러 개인 경우 송달료·증지대가 증가합니다. "
            "위 금액은 임대인 1명·임차인 1명·주택 1개 기준입니다. "
            "송달 지연·재송달 시 추가 비용이 발생할 수 있습니다."
        ),
    },
    # ────────────────────────────────────────────────────────────────────────
    # 【2】소액사건 — 소가에 따라 계산
    # ────────────────────────────────────────────────────────────────────────
    {
        "procedure_name": "소액사건",
        "fixed_cost_total": None,  # 고정 금액 없음
        "fixed_cost_breakdown": None,
        # 【공식】GPT가 이 공식대로만 계산하도록 프롬프트에 주입할 것
        "variable_cost_formula": (
            "[인지대] 소가(=청구 보증금액)에 따라 계산:\n"
            "  · 소가 1천만원 미만: 소가 × 50 / 10,000\n"
            "  · 소가 1천만원 이상 1억원 미만: 소가 × 45 / 10,000 + 5,000원\n"
            "  · 소가 1억원 이상 10억원 미만: 소가 × 40 / 10,000 + 55,000원\n"
            "  · 소가 10억원 이상: 소가 × 35 / 10,000 + 555,000원\n"
            "  ※ 계산액이 1,000원 미만이면 1,000원, 100원 미만 단수는 절사\n"
            "\n"
            "[송달료] 당사자수 × 5,500원 × 10회분\n"
            "  · 원고1·피고1이면: 2 × 5,500 × 10 = 110,000원"
        ),
        "eligibility": "소가(청구금액) 3,000만원 이하인 민사사건",
        "cost_source": (
            "민사소송 등 인지법 제2조 / 송달료규칙의 시행에 따른 업무처리요령 별표1"
        ),
        "cost_caution": (
            "당사자 수가 늘어나면 송달료가 증가합니다. "
            "변론이 길어지면 송달료를 추가 납부해야 할 수 있습니다."
        ),
    },
    # ────────────────────────────────────────────────────────────────────────
    # 【3】일반소송 — 소가에 따라 계산 (송달료 회수가 다름)
    # ────────────────────────────────────────────────────────────────────────
    {
        "procedure_name": "일반소송",
        "fixed_cost_total": None,
        "fixed_cost_breakdown": None,
        "variable_cost_formula": (
            "[인지대] 소액사건과 동일한 공식:\n"
            "  · 소가 1천만원 미만: 소가 × 50 / 10,000\n"
            "  · 소가 1천만원 이상 1억원 미만: 소가 × 45 / 10,000 + 5,000원\n"
            "  · 소가 1억원 이상 10억원 미만: 소가 × 40 / 10,000 + 55,000원\n"
            "  · 소가 10억원 이상: 소가 × 35 / 10,000 + 555,000원\n"
            "  ※ 계산액이 1,000원 미만이면 1,000원, 100원 미만 단수는 절사\n"
            "\n"
            "[송달료] 당사자수 × 5,500원 × 15회분  ← 소액사건(10회)보다 많음\n"
            "  · 원고1·피고1이면: 2 × 5,500 × 15 = 165,000원"
        ),
        "eligibility": "소가 3,000만원 초과 (소액사건 대상이 아닌 경우)",
        "cost_source": (
            "민사소송 등 인지법 제2조 / 송달료규칙의 시행에 따른 업무처리요령 별표1"
        ),
        "cost_caution": (
            "항소 시 인지대는 1심의 1.5배, 상고 시 2배입니다. "
            "패소하면 상대방 소송비용도 부담할 수 있습니다."
        ),
    },
    # ────────────────────────────────────────────────────────────────────────
    # 【4】내용증명 — 법원 절차가 아님 (우체국)
    # ────────────────────────────────────────────────────────────────────────
    {
        "procedure_name": "내용증명",
        "fixed_cost_total": None,
        "fixed_cost_breakdown": None,
        "variable_cost_formula": None,
        "eligibility": "제한 없음. 누구나 언제든 발송 가능",
        # ⚠️ 정직하게: 우체국 요금은 공식 자료를 확보하지 못했습니다.
        #    지어내지 않고 "확인 필요"로 안내합니다.
        "cost_source": "우체국 소관 (법원 수수료 아님)",
        "cost_caution": (
            "내용증명은 법원이 아닌 우체국 서비스입니다. "
            "요금은 매수·등기료에 따라 달라지므로 우체국(epost.go.kr) 또는 "
            "가까운 우체국에서 확인하세요."
        ),
    },
    # ────────────────────────────────────────────────────────────────────────
    # 【5】경매 배당 — 임차인이 신청하는 게 아님
    # ────────────────────────────────────────────────────────────────────────
    {
        "procedure_name": "경매 배당",
        "fixed_cost_total": None,
        "fixed_cost_breakdown": None,
        "variable_cost_formula": None,
        "eligibility": (
            "임대인 소유 주택이 경매에 들어간 경우, "
            "배당요구 종기일까지 배당요구를 한 임차인"
        ),
        # ⚠️ 중요: 배당요구 자체는 임차인이 경매를 신청하는 게 아니라
        #          이미 진행 중인 경매에 참여하는 것이라 별도 신청비용이 크지 않음
        "cost_source": "법원 경매 절차 (개별 확인 필요)",
        "cost_caution": (
            "배당요구는 이미 진행 중인 경매에 참여하는 절차로, "
            "임차인이 경매를 신청하는 경우와 비용이 다릅니다. "
            "구체적 비용은 관할 법원 경매계에 확인하세요."
        ),
    },
]


# ════════════════════════════════════════════════════════════════════════════════
# 【실행 함수】
# ════════════════════════════════════════════════════════════════════════════════


def seed_region_tiers(cur):
    """
    【시드 1】지역별 소액임차인 기준

    ⚠️ 마이그레이션에서 테이블을 새로 만들었으므로 비어있는 상태입니다.
    """
    print("\n【1】region_standards 시드 중...")

    # 【기존 데이터 정리】재실행해도 중복 안 생기게
    cur.execute("DELETE FROM region_standards")

    for tier in REGION_TIERS:
        cur.execute(
            """
            INSERT INTO region_standards (
                tier_name, tier_description,
                deposit_threshold, max_priority_payment,
                caution_note, legal_basis
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
            (
                tier["tier_name"],
                tier["tier_description"],
                tier["deposit_threshold"],
                tier["max_priority_payment"],
                tier["caution_note"],
                tier["legal_basis"],
            ),
        )

        # 【확인 출력】억 단위로 보기 좋게
        thr = tier["deposit_threshold"] / 100_000_000
        pay = tier["max_priority_payment"] / 10_000
        print(
            f"  ✓ {tier['tier_name']:12s} "
            f"보증금 {thr:.2f}억 이하 → 최우선변제 {pay:,.0f}만원"
        )

    print(f"  → {len(REGION_TIERS)}건 입력 완료")


def seed_procedure_costs(cur):
    """
    【시드 2】절차별 공식 비용
    """
    print("\n【2】procedure_info 비용 정보 업데이트 중...")

    for proc in PROCEDURE_COSTS:
        cur.execute(
            """
            UPDATE procedure_info
            SET fixed_cost_total      = %s,
                fixed_cost_breakdown  = %s,
                variable_cost_formula = %s,
                eligibility           = %s,
                cost_source           = %s,
                cost_caution          = %s,
                updated_at            = NOW()
            WHERE procedure_name = %s
        """,
            (
                proc["fixed_cost_total"],
                proc["fixed_cost_breakdown"],
                proc["variable_cost_formula"],
                proc["eligibility"],
                proc["cost_source"],
                proc["cost_caution"],
                proc["procedure_name"],
            ),
        )

        # 【확인】UPDATE가 실제로 됐는지
        if cur.rowcount == 0:
            print(f"  ⚠️  '{proc['procedure_name']}' — 해당 행이 없습니다!")
            print(f"      procedure_info의 procedure_name을 확인하세요.")
        else:
            # 고정비용 있으면 금액, 없으면 "공식 기반"
            if proc["fixed_cost_total"]:
                cost_desc = f"{proc['fixed_cost_total']:,}원 (고정)"
            elif proc["variable_cost_formula"]:
                cost_desc = "소가 기반 계산 공식"
            else:
                cost_desc = "확인 필요 안내"

            print(f"  ✓ {proc['procedure_name']:14s} → {cost_desc}")


def verify(cur):
    """
    【검증】입력된 데이터 확인

    """
    print("\n【검증】입력 결과 확인")
    print("=" * 74)

    # 【1】서울 기준이 제대로 들어갔나 (가장 중요)
    cur.execute("""
        SELECT deposit_threshold, max_priority_payment
        FROM region_standards
        WHERE tier_name = '서울특별시'
    """)
    row = cur.fetchone()

    if row and row[0] == 165_000_000:
        print("  ✅ 서울 소액임차인 기준: 1억 6,500만원 (정상)")
    else:
        print(f"  ❌ 서울 기준이 이상합니다: {row}")

    # 【2】임차권등기명령 비용
    cur.execute("""
        SELECT fixed_cost_total
        FROM procedure_info
        WHERE procedure_name = '임차권등기명령'
    """)
    row = cur.fetchone()

    if row and row[0] == 43_400:
        print("  ✅ 임차권등기명령 비용: 43,400원 (정상)")
    else:
        print(f"  ❌ 임차권등기명령 비용이 이상합니다: {row}")

    # 【3】전체 건수
    cur.execute("SELECT COUNT(*) FROM region_standards")
    print(f"  ✅ region_standards: {cur.fetchone()[0]}건")

    cur.execute("SELECT COUNT(*) FROM procedure_info WHERE cost_source IS NOT NULL")
    print(f"  ✅ procedure_info (비용 입력됨): {cur.fetchone()[0]}건")

    print("=" * 74)


def main():
    """
    【메인】시드 실행
    """
    print("=" * 74)
    print("【C파트 공식 비용 데이터 시드】")
    print("=" * 74)
    print("\n출처:")
    print("  · 주택임대차보호법 시행령 제11조 (2023.2.21 개정)")
    print("  · 민사소송 등 인지법 제2조")
    print("  · 송달료규칙 별표1")
    print("  · 법제처 찾기쉬운 생활법령정보 (2026.6.15 기준)")

    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        print(f"\n✅ DB 접속 성공")

    except Exception as e:
        print(f"\n❌ DB 접속 실패: {e}")
        return

    try:
        seed_region_tiers(cur)
        seed_procedure_costs(cur)

        # 【커밋】여기까지 성공해야 저장
        conn.commit()
        print("\n✅ 커밋 완료")

        verify(cur)

    except Exception as e:
        # 【롤백】중간에 실패하면 전부 되돌림
        conn.rollback()
        print(f"\n❌ 시드 실패 (롤백됨): {e}")
        print("\n확인할 것:")
        print("  1. 마이그레이션을 먼저 적용했나요? → alembic upgrade head")
        print("  2. 컬럼명이 마이그레이션과 일치하나요?")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
