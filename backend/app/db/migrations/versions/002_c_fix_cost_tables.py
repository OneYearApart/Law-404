"""002_c_fix_cost_tables

Revision ID: 002_c_fix_cost_tables
Revises: 001_c_alter_part_metadata
"""

from alembic import op
import sqlalchemy as sa


# 【Alembic 식별자】
revision = "002_c_fix_cost_tables"
down_revision = "001_c_part_metadata"
branch_labels = None
depends_on = None


def upgrade():
    """
    【업그레이드】테이블 재설계

    """

    # ════════════════════════════════════════════════════════════════════════
    # 【1】region_standards 재설계
    # ════════════════════════════════════════════════════════════════════════

    op.drop_table("region_standards")

    op.create_table(
        "region_standards",
        sa.Column("id", sa.Integer, primary_key=True),

        # 【법령상 구분】주택임대차보호법 시행령 제11조의 4단계
        # 예: "서울특별시", "과밀억제권역", "광역시", "그 밖의 지역"
        sa.Column("tier_name", sa.String(50), nullable=False, unique=True),

        # 【적용 범위 설명】어느 지역이 이 등급에 속하는지
        # 예: "수도권정비계획법상 과밀억제권역(서울 제외), 세종, 용인, 화성, 김포"
        sa.Column("tier_description", sa.Text, nullable=False),

        # 【소액임차인 보증금 기준】이 금액 이하여야 소액임차인
        # 서울 = 165,000,000원
        sa.Column("deposit_threshold", sa.BigInteger, nullable=False),

        # 【최우선변제금 한도】실제로 우선 배당받는 최대 금액
        # 서울 = 55,000,000원
        # ⚠️ 보증금 전액이 아니라 이 금액까지만 최우선변제됨!
        sa.Column("max_priority_payment", sa.BigInteger, nullable=False),

        # 【주의사항】사용자에게 함께 안내해야 할 내용
        # 경기/인천처럼 시·군마다 달라지는 경우 여기에 명시
        sa.Column("caution_note", sa.Text, nullable=True),

        # 【근거】법령명 + 개정일
        sa.Column("legal_basis", sa.String(200), nullable=False),

        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )

    # ════════════════════════════════════════════════════════════════════════
    # 【2】procedure_info에 수수료 컬럼 추가
    # ════════════════════════════════════════════════════════════════════════
    # 기존 컬럼(id, procedure_name, description)은 유지하고 추가만 합니다.

    op.add_column("procedure_info",
        sa.Column("fixed_cost_total", sa.Integer, nullable=True,
                  comment="고정 비용 총액(원). 소가와 무관한 절차만 값이 있음"))

    op.add_column("procedure_info",
        sa.Column("fixed_cost_breakdown", sa.Text, nullable=True,
                  comment="고정 비용 항목별 내역"))

    # 【변동 비용】소가에 따라 계산되는 절차용 (소액사건, 일반소송)
    # 계산 방법을 텍스트로 저장 → 프롬프트에 그대로 주입
    op.add_column("procedure_info",
        sa.Column("variable_cost_formula", sa.Text, nullable=True,
                  comment="소가 기반 비용 계산 공식. GPT가 이 공식대로만 계산하도록"))

    # 【적용 조건】이 절차를 쓸 수 있는 조건
    # 예: 소액사건 → "소가 3,000만원 이하"
    op.add_column("procedure_info",
        sa.Column("eligibility", sa.Text, nullable=True,
                  comment="이 절차를 신청할 수 있는 조건"))

    # 【근거】출처 명시 — 답변에 함께 표시할 것
    op.add_column("procedure_info",
        sa.Column("cost_source", sa.String(200), nullable=True,
                  comment="비용 정보의 출처 (법령명 + 기준일)"))

    # 【주의사항】비용이 달라질 수 있는 경우
    # 예: "임대인이 여러 명이면 송달료가 증가합니다"
    op.add_column("procedure_info",
        sa.Column("cost_caution", sa.Text, nullable=True,
                  comment="비용 변동 요인 안내"))


def downgrade():
    """
    【다운그레이드】원래대로 되돌리기 - 테이블 구조만 
    """

    # 【procedure_info】추가한 컬럼 제거
    op.drop_column("procedure_info", "cost_caution")
    op.drop_column("procedure_info", "cost_source")
    op.drop_column("procedure_info", "eligibility")
    op.drop_column("procedure_info", "variable_cost_formula")
    op.drop_column("procedure_info", "fixed_cost_breakdown")
    op.drop_column("procedure_info", "fixed_cost_total")

    # 【region_standards】원래 구조로 복원 (데이터는 없음)
    op.drop_table("region_standards")

    op.create_table(
        "region_standards",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("region", sa.String(50), nullable=False),
        sa.Column("small_deposit_threshold", sa.Integer, nullable=False),
        sa.Column("lawyer_fee_rate_min", sa.Integer, nullable=False),
        sa.Column("lawyer_fee_rate_max", sa.Integer, nullable=False),
        sa.Column("data_source", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )