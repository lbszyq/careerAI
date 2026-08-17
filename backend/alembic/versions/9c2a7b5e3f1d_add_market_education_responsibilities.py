"""：market_data 增加 education_requirement（学历要求）+ responsibilities（职责）两列。

- education_requirement：String nullable，值域 不限/大专/本科/硕士/博士（可带「及以上」）
- responsibilities：JSONB nullable，字符串数组（对齐 required_skills 数组形态）
- 两列下沉到 market_data 表并注入 RAG 上下文 / jd_summary（内部 AI 链路用），
  不改变 API 响应结构（schemas/market.py、market_service.py 不改，market-contract v1.1 未收口这两字段）；
  契约偏离由 项目负责人 验证后派 同步（market-contract 新增两字段、data-model.md）。
- 值域校验由应用层（seed validate_record）承担，不在迁移内加 CHECK（与 city_tier/trend/source_type 一致）。
- 数据回填不在迁移内执行：迁移保持 Schema 变更最小化，回填为可重入数据采集步骤（seed 幂等重插）。

Revision ID: 9c2a7b5e3f1d
Revises: e5f7a9c1b3d2
Create Date: 2026-08-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '9c2a7b5e3f1d'
down_revision: Union[str, None] = 'e5f7a9c1b3d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'market_data',
        sa.Column('education_requirement', sa.String(length=32), nullable=True),
    )
    op.add_column(
        'market_data',
        sa.Column('responsibilities', postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('market_data', 'responsibilities')
    op.drop_column('market_data', 'education_requirement')
