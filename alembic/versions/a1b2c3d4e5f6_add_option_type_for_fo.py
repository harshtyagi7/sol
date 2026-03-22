"""add option_type for F&O support

Revision ID: a1b2c3d4e5f6
Revises: f5493e750715
Create Date: 2026-03-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f5493e750715"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add option_type to the three instrument-carrying tables.
    # Nullable — existing equity rows will have NULL (treated as equity/spot).
    op.add_column("trade_proposals", sa.Column("option_type", sa.String(5), nullable=True))
    op.add_column("positions",       sa.Column("option_type", sa.String(5), nullable=True))
    op.add_column("strategy_trades", sa.Column("option_type", sa.String(5), nullable=True))


def downgrade() -> None:
    op.drop_column("strategy_trades", "option_type")
    op.drop_column("positions",       "option_type")
    op.drop_column("trade_proposals", "option_type")
