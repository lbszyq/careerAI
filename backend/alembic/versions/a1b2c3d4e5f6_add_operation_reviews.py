"""add operation_reviews table ( critical-operation audit & confirmation)

Revision ID: a1b2c3d4e5f6
Revises: 2a2911abafba
Create Date: 2026-08-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '2a2911abafba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'operation_reviews',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('resource_type', sa.String(length=32), nullable=False),
        sa.Column('resource_id', sa.String(length=64), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_operation_reviews_user_id'), 'operation_reviews', ['user_id'], unique=False)
    op.create_index(op.f('ix_operation_reviews_action'), 'operation_reviews', ['action'], unique=False)
    op.create_index(op.f('ix_operation_reviews_status'), 'operation_reviews', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_operation_reviews_status'), table_name='operation_reviews')
    op.drop_index(op.f('ix_operation_reviews_action'), table_name='operation_reviews')
    op.drop_index(op.f('ix_operation_reviews_user_id'), table_name='operation_reviews')
    op.drop_table('operation_reviews')
