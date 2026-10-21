"""settings table for UI preferences

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20 18:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('setting',
    sa.Column('key', sa.String(length=50), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('key', name=op.f('pk_setting'))
    )


def downgrade() -> None:
    op.drop_table('setting')
