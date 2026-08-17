"""迁移：新增 trace_spans 表 + task_jobs.trace_id 列。

- trace_spans：任务级链路追踪 span（architecture.md），字段 = id / trace_id /
  parent_span_id / span_type(task|agent|llm|rag) / name / status(running|succeeded|failed) /
  error_message / duration_ms / tokens / cost / hit_count / created_at。
- trace_id 一对多，仅建普通（非 UNIQUE）索引，严禁 UNIQUE。
- task_jobs.trace_id 为可空 UUID（历史任务 NULL），trace_id 在 API 进程生成、贯穿 span。

Revision ID: 8c5d2e7f4a1b
Revises: 2a2911abafba
Create Date: 2026-08-13 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8c5d2e7f4a1b'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) trace_spans 表
    op.create_table(
        'trace_spans',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('trace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('parent_span_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('span_type', sa.String(length=16), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='running', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), server_default='0', nullable=False),
        sa.Column('tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cost', sa.Float(), server_default='0', nullable=False),
        sa.Column('hit_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    # trace_id 一对多：只建普通索引，严禁 UNIQUE
    op.create_index(op.f('ix_trace_spans_trace_id'), 'trace_spans', ['trace_id'], unique=False)
    op.create_index(op.f('ix_trace_spans_span_type'), 'trace_spans', ['span_type'], unique=False)

    # 2) task_jobs.trace_id（可空，历史任务 NULL）
    op.add_column('task_jobs', sa.Column('trace_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f('ix_task_jobs_trace_id'), 'task_jobs', ['trace_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_task_jobs_trace_id'), table_name='task_jobs')
    op.drop_column('task_jobs', 'trace_id')
    op.drop_index(op.f('ix_trace_spans_span_type'), table_name='trace_spans')
    op.drop_index(op.f('ix_trace_spans_trace_id'), table_name='trace_spans')
    op.drop_table('trace_spans')
