"""增量迁移 2：market_data 补齐时间维度 + 业务复合索引 + pgvector HNSW 向量索引（增量 2 / T）。

- data_quarter：数据季度（YYYYQn，如 2026Q1；年度工资价位存 YYYY），支撑需求趋势按季度回溯
- city_tier：城市等级（一线/新一线/二线/三线/四线及以下），支撑常模分组（B-002）
- 索引：旧 3 列索引 ix_market_data_city_industry_job 被 4 列 ix_market_data_city_industry_job_quarter
  取代（前三列为前缀，4 列索引可覆盖旧查询，避免冗余）
- 向量索引：ix_market_data_embedding_hnsw（HNSW + vector_cosine_ops，bge-m3 1024 维，余弦相似 <=>）

Revision ID: 2d36e64f1408
Revises: d2baf00450de
Create Date: 2026-08-05 15:50:40.527683

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2d36e64f1408'
down_revision: Union[str, None] = 'd2baf00450de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('market_data', sa.Column('data_quarter', sa.String(length=16), nullable=True))
    op.add_column('market_data', sa.Column('city_tier', sa.String(length=16), nullable=True))
    op.drop_index('ix_market_data_city_industry_job', table_name='market_data')
    op.create_index(
        'ix_market_data_city_industry_job_quarter',
        'market_data',
        ['city', 'industry', 'job_title', 'data_quarter'],
        unique=False,
    )
    # pgvector HNSW 向量索引（余弦距离；bge-m3 1024 维 embedding）
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_market_data_embedding_hnsw '
        'ON market_data USING hnsw (embedding vector_cosine_ops)'
    )


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS ix_market_data_embedding_hnsw')
    op.drop_index('ix_market_data_city_industry_job_quarter', table_name='market_data')
    op.create_index('ix_market_data_city_industry_job', 'market_data', ['city', 'industry', 'job_title'], unique=False)
    op.drop_column('market_data', 'city_tier')
    op.drop_column('market_data', 'data_quarter')
