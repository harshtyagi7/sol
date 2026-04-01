"""add sl_tp_order_ids to positions

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f6
Create Date: 2026-04-01
"""
from alembic import op
import sqlalchemy as sa

revision = 'b1c2d3e4f5a6'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('positions', sa.Column('kite_order_id', sa.String(50), nullable=True))
    op.add_column('positions', sa.Column('sl_order_id', sa.String(50), nullable=True))
    op.add_column('positions', sa.Column('tp_order_id', sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column('positions', 'tp_order_id')
    op.drop_column('positions', 'sl_order_id')
    op.drop_column('positions', 'kite_order_id')
