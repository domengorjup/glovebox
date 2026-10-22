"""preset.locked flag

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('preset', schema=None) as batch_op:
        batch_op.add_column(sa.Column('locked', sa.Boolean(), nullable=False,
                                      server_default=sa.text('0')))


def downgrade() -> None:
    with op.batch_alter_table('preset', schema=None) as batch_op:
        batch_op.drop_column('locked')
