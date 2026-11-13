"""drop historical global idempotency key uniqueness

Revision ID: e4a6c8d9f012
Revises: c3f1a9e7d2b4
"""
from alembic import op
import sqlalchemy as sa

revision = "e4a6c8d9f012"
down_revision = "c3f1a9e7d2b4"
branch_labels = None
depends_on = None


def _drop_legacy_unique(table):
    """Remove only a single-column idempotency uniqueness left by old schemas."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for constraint in inspector.get_unique_constraints(table):
        if constraint.get("column_names") == ["idempotency_key"] and constraint.get("name"):
            op.drop_constraint(constraint["name"], table, type_="unique")
    # SQLite represents a hand-created legacy uniqueness as an index rather than
    # a named table constraint; production PostgreSQL uses the branch above.
    for index in inspector.get_indexes(table):
        if index.get("unique") and index.get("column_names") == ["idempotency_key"]:
            op.drop_index(index["name"], table_name=table)


def upgrade():
    _drop_legacy_unique("donation")
    _drop_legacy_unique("payout")


def downgrade():
    # Restoring a global uniqueness constraint can fail after valid per-user keys
    # exist, so downgrade deliberately preserves the safer scoped constraint.
    pass
