"""add achievements / reassessments tables ( feedback loop )

Revision ID: c1a2b3d4e5f6
Revises: a50cb7d4a7aa
Create Date: 2026-08-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = 'a50cb7d4a7aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'achievements',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('url', sa.String(length=500), nullable=False),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('stage', sa.String(length=16), nullable=True),
        sa.Column('task_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['plan_id'], ['growth_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['plan_tasks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_achievements_plan_id'), 'achievements', ['plan_id'], unique=False)

    op.create_table(
        'reassessments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('task_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='succeeded', nullable=False),
        sa.Column('decision', sa.String(length=16), server_default='undecided', nullable=False),
        sa.Column('summary', sa.String(length=500), nullable=True),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['plan_id'], ['growth_plans.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['task_jobs.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_reassessments_plan_id'), 'reassessments', ['plan_id'], unique=False)
    op.create_index(op.f('ix_reassessments_task_id'), 'reassessments', ['task_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_reassessments_task_id'), table_name='reassessments')
    op.drop_index(op.f('ix_reassessments_plan_id'), table_name='reassessments')
    op.drop_table('reassessments')
    op.drop_index(op.f('ix_achievements_plan_id'), table_name='achievements')
    op.drop_table('achievements')
