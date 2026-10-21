"""expense.odometer_estimated flag

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('expense', schema=None) as batch_op:
        batch_op.add_column(sa.Column('odometer_estimated', sa.Boolean(), nullable=False,
                                      server_default=sa.text('0')))


def downgrade() -> None:
    with op.batch_alter_table('expense', schema=None) as batch_op:
        batch_op.drop_column('odometer_estimated')
