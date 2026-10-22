"""vehicle details: VIN, model year, engine, tyres, insurance, registration

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22 15:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

_COLUMNS = (
    ('vin', sa.String(length=30)),
    ('model_year', sa.Integer()),
    ('engine', sa.String(length=100)),
    ('tyre_size', sa.String(length=50)),
    ('insurance_policy', sa.String(length=100)),
    ('insurance_valid_until', sa.Date()),
    ('registration_valid_until', sa.Date()),
)


def upgrade() -> None:
    with op.batch_alter_table('vehicle', schema=None) as batch_op:
        for name, type_ in _COLUMNS:
            batch_op.add_column(sa.Column(name, type_, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('vehicle', schema=None) as batch_op:
        for name, _ in reversed(_COLUMNS):
            batch_op.drop_column(name)
