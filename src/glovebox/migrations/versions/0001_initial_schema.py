"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-20 14:38:08.940285
"""
from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('import_batch',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('format', sa.String(length=20), nullable=False),
    sa.Column('filename', sa.String(length=255), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('refuels_imported', sa.Integer(), nullable=False),
    sa.Column('expenses_imported', sa.Integer(), nullable=False),
    sa.Column('duplicates_skipped', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_import_batch'))
    )
    op.create_table('vehicle',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('make', sa.String(length=100), nullable=True),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('plate', sa.String(length=30), nullable=True),
    sa.Column('fuel_type', sa.String(length=50), nullable=True),
    sa.Column('initial_odometer', sa.Float(), nullable=True),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_vehicle'))
    )
    with op.batch_alter_table('vehicle', schema=None) as batch_op:
        batch_op.create_index('uq_vehicle_active_name', ['name'], unique=True, sqlite_where=sa.text('archived = 0'))

    op.create_table('expense',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('vehicle_id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('odometer_km', sa.Float(), nullable=True),
    sa.Column('category', sa.Enum('maintenance', 'insurance', 'registration', 'other', name='expense_category', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('amount_cents', sa.Integer(), nullable=False),
    sa.Column('coverage_start', sa.Date(), nullable=True),
    sa.Column('coverage_end', sa.Date(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('source_ref', sa.String(length=100), nullable=True),
    sa.Column('import_batch_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("category IN ('maintenance', 'insurance', 'registration', 'other')", name=op.f('ck_expense_expense_category')),
    sa.ForeignKeyConstraint(['import_batch_id'], ['import_batch.id'], name=op.f('fk_expense_import_batch_id_import_batch'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicle.id'], name=op.f('fk_expense_vehicle_id_vehicle'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_expense'))
    )
    with op.batch_alter_table('expense', schema=None) as batch_op:
        batch_op.create_index('ix_expense_dedupe', ['vehicle_id', 'date', 'category', 'amount_cents'], unique=False)
        batch_op.create_index(batch_op.f('ix_expense_import_batch_id'), ['import_batch_id'], unique=False)

    op.create_table('station',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=150), nullable=False),
    sa.Column('brand', sa.String(length=100), nullable=True),
    sa.Column('location', sa.String(length=200), nullable=True),
    sa.Column('import_batch_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['import_batch_id'], ['import_batch.id'], name=op.f('fk_station_import_batch_id_import_batch'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_station')),
    sa.UniqueConstraint('name', 'location', name=op.f('uq_station_name'))
    )
    op.create_table('refuel',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('vehicle_id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('time', sa.Time(), nullable=True),
    sa.Column('odometer_km', sa.Float(), nullable=False),
    sa.Column('litres_milli', sa.Integer(), nullable=False),
    sa.Column('price_per_litre_milli', sa.Integer(), nullable=False),
    sa.Column('total_cents', sa.Integer(), nullable=False),
    sa.Column('derived_field', sa.Enum('litres', 'price_per_litre', 'total', name='derived_field', native_enum=False, create_constraint=True, length=20), nullable=True),
    sa.Column('station_id', sa.Integer(), nullable=True),
    sa.Column('is_full', sa.Boolean(), nullable=False),
    sa.Column('missed_previous', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('source_ref', sa.String(length=100), nullable=True),
    sa.Column('import_batch_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("derived_field IN ('litres', 'price_per_litre', 'total')", name=op.f('ck_refuel_derived_field')),
    sa.ForeignKeyConstraint(['import_batch_id'], ['import_batch.id'], name=op.f('fk_refuel_import_batch_id_import_batch'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['station_id'], ['station.id'], name=op.f('fk_refuel_station_id_station'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicle.id'], name=op.f('fk_refuel_vehicle_id_vehicle'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_refuel'))
    )
    with op.batch_alter_table('refuel', schema=None) as batch_op:
        batch_op.create_index('ix_refuel_dedupe', ['vehicle_id', 'date', 'odometer_km'], unique=False)
        batch_op.create_index(batch_op.f('ix_refuel_import_batch_id'), ['import_batch_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_refuel_station_id'), ['station_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('refuel', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_refuel_station_id'))
        batch_op.drop_index(batch_op.f('ix_refuel_import_batch_id'))
        batch_op.drop_index('ix_refuel_dedupe')

    op.drop_table('refuel')
    op.drop_table('station')
    with op.batch_alter_table('expense', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_expense_import_batch_id'))
        batch_op.drop_index('ix_expense_dedupe')

    op.drop_table('expense')
    with op.batch_alter_table('vehicle', schema=None) as batch_op:
        batch_op.drop_index('uq_vehicle_active_name', sqlite_where=sa.text('archived = 0'))

    op.drop_table('vehicle')
    op.drop_table('import_batch')
