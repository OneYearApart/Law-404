"""
================================================================================
【Alembic 마이그레이션】 C파트 판례 메타데이터 테이블 확장

Revision ID: 001_c_part_metadata
Create Date: 2026-07-11
================================================================================
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
# 🔍 이 ID는 알렘빅이 "어느 마이그레이션이 실행되었는지"를 추적합니다.
revision = '001_c_part_metadata'
down_revision = "3e54a112e80e"  # 이것이 첫 번째 마이그레이션이라는 뜻
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    🔼 업그레이드 (DB 구조 업데이트)
    """
    
    # ────────────────────────────────────────────────────────────────────────
    # 1. legal_documents_c 테이블 ALTER (기존 테이블에 컬럼 추가)
    # ────────────────────────────────────────────────────────────────────────
    
    # 추가되는 컬럼 (공식 데이터만):
    # • court_level: 대법원/고등법원 (국토교통부 기준)
    # • case_year: 판례 연도 (판례에서 나옴)
    # • ruling_type: 임차인 승소/임대인 승소 (판례에서 나옴)
    # • appeal_outcome: 상소 없음/기각/인용 (판례에서 나옴)
    # • related_procedures: JSON으로 연관 절차 저장
    
    op.add_column('legal_documents_c', sa.Column('court_level', sa.Integer(), nullable=True))
    op.add_column('legal_documents_c', sa.Column('case_year', sa.Integer(), nullable=True))
    op.add_column('legal_documents_c', sa.Column('ruling_type', sa.String(50), nullable=True))
    op.add_column('legal_documents_c', sa.Column('appeal_outcome', sa.String(50), nullable=True))
    op.add_column('legal_documents_c', sa.Column('related_procedures', sa.Text(), nullable=True))
    
    op.create_index('idx_legal_documents_c_court_level', 'legal_documents_c', ['court_level'])
    op.create_index('idx_legal_documents_c_case_year', 'legal_documents_c', ['case_year'], postgresql_ops={'case_year': 'DESC'})
    op.create_index('idx_legal_documents_c_ruling_type', 'legal_documents_c', ['ruling_type'])

    # ────────────────────────────────────────────────────────────────────────
    # 2. region_standards 테이블 생성 (지역별 표준 정보)
    # ────────────────────────────────────────────────────────────────────────
    
    op.create_table(
        'region_standards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('region', sa.String(50), nullable=False),
        sa.Column('small_deposit_threshold', sa.Integer(), nullable=False),
        sa.Column('lawyer_fee_rate_min', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('lawyer_fee_rate_max', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('data_source', sa.String(100), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('region', name='uq_region_standards_region')
    )
    op.create_index('idx_region_standards_region', 'region_standards', ['region'])

    # ────────────────────────────────────────────────────────────────────────
    # 3. procedure_info 테이블 생성 (절차별 기본 정보)
    # ────────────────────────────────────────────────────────────────────────
    
    op.create_table(
        'procedure_info',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('procedure_name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('procedure_name', name='uq_procedure_info_name')
    )
    op.create_index('idx_procedure_info_name', 'procedure_info', ['procedure_name'])


def downgrade() -> None:
    """
    🔽 다운그레이드 (DB 구조를 이전 상태로 되돌림)
    """
    
    # 만든 것을 역순으로 삭제
    
    op.drop_index('idx_procedure_info_name', table_name='procedure_info')
    op.drop_table('procedure_info')

    op.drop_index('idx_region_standards_region', table_name='region_standards')
    op.drop_table('region_standards')

    # 추가한 인덱스와 컬럼을 삭제 (역순)
    op.drop_index('idx_legal_documents_c_ruling_type', table_name='legal_documents_c')
    op.drop_index('idx_legal_documents_c_case_year', table_name='legal_documents_c')
    op.drop_index('idx_legal_documents_c_court_level', table_name='legal_documents_c')
    
    op.drop_column('legal_documents_c', 'related_procedures')
    op.drop_column('legal_documents_c', 'appeal_outcome')
    op.drop_column('legal_documents_c', 'ruling_type')
    op.drop_column('legal_documents_c', 'case_year')
    op.drop_column('legal_documents_c', 'court_level')