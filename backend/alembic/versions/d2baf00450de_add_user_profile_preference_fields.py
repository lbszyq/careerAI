"""增量迁移 1：user_profiles 补齐偏好与毕业年份字段（增量 1 / T）。

- graduation_year：毕业年份（「同届」常模维度 + C-002 报告最低门槛）
- preferred_cities / preferred_industries：意向城市/行业（≤5，应用层校验）
- expected_salary：期望月薪（元/月）

Revision ID: d2baf00450de
Revises: 15528104623c
Create Date: 2026-08-05 15:50:37.915510

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd2baf00450de'
down_revision: Union[str, None] = '15528104623c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_profiles', sa.Column('graduation_year', sa.Integer(), nullable=True))
    op.add_column(
        'user_profiles',
        sa.Column('preferred_cities', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    )
    op.add_column(
        'user_profiles',
        sa.Column('preferred_industries', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    )
    op.add_column('user_profiles', sa.Column('expected_salary', sa.Numeric(precision=12, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column('user_profiles', 'expected_salary')
    op.drop_column('user_profiles', 'preferred_industries')
    op.drop_column('user_profiles', 'preferred_cities')
    op.drop_column('user_profiles', 'graduation_year')
