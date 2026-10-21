"""user presets table; widen format and source columns to 50 characters

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('preset',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_preset')),
    sa.UniqueConstraint('slug', name=op.f('uq_preset_slug'))
    )
    _resize(50, 20)


def downgrade() -> None:
    # Values longer than 20 characters (only user-preset ids) are cut first.
    for table, column in (('import_batch', 'format'), ('refuel', 'source'), ('expense', 'source')):
        op.execute(sa.text(f'UPDATE {table} SET {column} = substr({column}, 1, 20)'))
    _resize(20, 50)
    op.drop_table('preset')


def _resize(new: int, old: int) -> None:
    with op.batch_alter_table('import_batch', schema=None) as batch_op:
        batch_op.alter_column('format', existing_type=sa.String(length=old),
                              type_=sa.String(length=new), existing_nullable=False)
    for table in ('refuel', 'expense'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.alter_column('source', existing_type=sa.String(length=old),
                                  type_=sa.String(length=new), existing_nullable=False)
