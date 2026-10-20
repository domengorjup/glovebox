"""Alembic environment; runs on a connection supplied by ``db.run_migrations``."""

from __future__ import annotations

from alembic import context

from glovebox.models import Base

connection = context.config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    render_as_batch=True,
)
with context.begin_transaction():
    context.run_migrations()
