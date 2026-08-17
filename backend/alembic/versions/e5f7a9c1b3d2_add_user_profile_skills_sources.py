"""迁移：user_profiles 新增 skills_sources（skills 并行 provenance 数组）。

- skills_sources：与 skills 索引对齐的 JSONB 数组，元素 ∈ {"literal","inferred"}，
  记录每个技能的来源（原文显式出现 / 蕴含反推），随画像落库（方案 b）。
- 可逆：downgrade drop_column；不影响存量数据（server_default '[]'，旧行自动为空数组）。

Revision ID: e5f7a9c1b3d2
Revises: 8c5d2e7f4a1b
Create Date: 2026-08-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e5f7a9c1b3d2'
down_revision: Union[str, None] = '8c5d2e7f4a1b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'user_profiles',
        sa.Column('skills_sources', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    )


def downgrade() -> None:
    op.drop_column('user_profiles', 'skills_sources')
