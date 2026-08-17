"""迁移：market_data 增加 source_type 列（来源类型，值域 official_stat/job_post/ai_infer）。

- 列可空：存量 335 条由 seed_market_data.py --backfill-source-type 幂等回填
  （307 条按幂等键匹配 JSON 的 source_type；28 条 legacy-jd 标 job_post）。
- 值域校验由应用层（seed validate_record / retriever._DATA_GRADE_MAP）承担；
  真实数据禁止 ai_infer（反幻觉底线）。
- 数据回填不在迁移内执行：迁移保持 Schema 变更最小化，回填为可重入数据修复步骤。

Revision ID: 2a2911abafba
Revises: c1a2b3d4e5f6
Create Date: 2026-08-12 18:11:30.849000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2a2911abafba'
down_revision: Union[str, None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("market_data", sa.Column("source_type", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("market_data", "source_type")