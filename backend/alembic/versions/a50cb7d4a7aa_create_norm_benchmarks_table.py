"""增量迁移 3：新建 norm_benchmarks 常模基准表（增量 3 / T，B-002/ 定案）。

分组维度：同届（graduation_year）× 城市等级（city_tier）× 专业大类（major_category）
指标：sample_size、前25%/中50%/后25% 分位阈值（salary_p25/p50/p75）、contains_employed、confidence
数据期：data_quarter（季度数据 YYYYQn；年度聚合存 YYYY）
约束：单元唯一键（graduation_year, city_tier, major_category, data_quarter）；
      单元样本 <30 由应用层降级「样本不足」（C-009，不落库拦截）

Revision ID: a50cb7d4a7aa
Revises: 2d36e64f1408
Create Date: 2026-08-05 15:50:43.562559

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a50cb7d4a7aa'
down_revision: Union[str, None] = '2d36e64f1408'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'norm_benchmarks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('graduation_year', sa.Integer(), nullable=False),
        sa.Column('city_tier', sa.String(length=16), nullable=False),
        sa.Column('major_category', sa.String(length=64), nullable=False),
        sa.Column('sample_size', sa.Integer(), nullable=False),
        sa.Column('salary_p25', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('salary_p50', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('salary_p75', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('contains_employed', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('confidence', sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column('data_quarter', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('sample_size >= 0', name='ck_norm_benchmarks_sample_size_nonneg'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'graduation_year', 'city_tier', 'major_category', 'data_quarter', name='uq_norm_benchmarks_unit'
        ),
    )
    op.create_index(
        'ix_norm_benchmarks_group', 'norm_benchmarks', ['graduation_year', 'city_tier', 'major_category'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_norm_benchmarks_group', table_name='norm_benchmarks')
    op.drop_table('norm_benchmarks')
