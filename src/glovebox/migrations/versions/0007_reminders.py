"""reminders: the reminder table and the import batch reminder count

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-23 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

_CATEGORIES = ('maintenance', 'insurance', 'registration', 'other')
_STATUSES = ('open', 'done')
_CAL_STATES = ('none', 'pending', 'synced', 'unchanged', 'error')


def upgrade() -> None:
    op.create_table('reminder',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('uid', sa.String(length=36), nullable=False),
    sa.Column('vehicle_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('category', sa.Enum(*_CATEGORIES, name='reminder_category', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('due_date', sa.Date(), nullable=False),
    sa.Column('lead_days', sa.Integer(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('status', sa.Enum(*_STATUSES, name='reminder_status', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('done_at', sa.DateTime(), nullable=True),
    sa.Column('expense_id', sa.Integer(), nullable=True),
    sa.Column('vehicle_field', sa.String(length=40), nullable=True),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('cal_entity', sa.String(length=255), nullable=True),
    sa.Column('cal_uid', sa.String(length=255), nullable=True),
    sa.Column('cal_state', sa.Enum(*_CAL_STATES, name='reminder_cal_state', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('cal_message', sa.Text(), nullable=True),
    sa.Column('cal_synced_revision', sa.Integer(), nullable=True),
    sa.Column('cal_synced_due', sa.Date(), nullable=True),
    sa.Column('import_batch_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('lead_days >= 0 AND lead_days <= 365', name=op.f('ck_reminder_lead_days')),
    sa.ForeignKeyConstraint(['expense_id'], ['expense.id'], name=op.f('fk_reminder_expense_id_expense'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['import_batch_id'], ['import_batch.id'], name=op.f('fk_reminder_import_batch_id_import_batch'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicle.id'], name=op.f('fk_reminder_vehicle_id_vehicle'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reminder')),
    sa.UniqueConstraint('uid', name=op.f('uq_reminder_uid'))
    )
    op.create_index(op.f('ix_reminder_vehicle_id'), 'reminder', ['vehicle_id'], unique=False)
    op.create_index(op.f('ix_reminder_import_batch_id'), 'reminder', ['import_batch_id'], unique=False)
    with op.batch_alter_table('import_batch', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reminders_imported', sa.Integer(), server_default=sa.text('0'), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('import_batch', schema=None) as batch_op:
        batch_op.drop_column('reminders_imported')
    op.drop_index(op.f('ix_reminder_import_batch_id'), table_name='reminder')
    op.drop_index(op.f('ix_reminder_vehicle_id'), table_name='reminder')
    op.drop_table('reminder')
