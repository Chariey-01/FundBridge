"""messaging tables: PIN credentials, phone preferences, support requests

Revision ID: c3f1a9e7d2b4
Revises: a0d4581f14e2
Create Date: 2026-11-11 12:00:00

"""
from alembic import op
import sqlalchemy as sa


revision = "c3f1a9e7d2b4"
down_revision = "a0d4581f14e2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "messaging_pin_credential",
        sa.Column("beneficiary_id", sa.String(length=36), nullable=False),
        sa.Column("pin_hash", sa.String(length=255), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["beneficiary_id"], ["beneficiary_profile.id"]),
        sa.PrimaryKeyConstraint("beneficiary_id"),
    )
    op.create_table(
        "messaging_preference",
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("opted_out", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("phone_number"),
    )
    op.create_table(
        "support_request",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("reference", sa.String(length=16), nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("beneficiary_id", sa.String(length=36), nullable=True),
        sa.Column("channel", sa.String(length=8), nullable=False),
        sa.Column("topic", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["beneficiary_id"], ["beneficiary_profile.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference"),
    )
    with op.batch_alter_table("support_request", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_support_request_phone_number"), ["phone_number"], unique=False)
        batch_op.create_index(batch_op.f("ix_support_request_beneficiary_id"), ["beneficiary_id"], unique=False)


def downgrade():
    with op.batch_alter_table("support_request", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_support_request_beneficiary_id"))
        batch_op.drop_index(batch_op.f("ix_support_request_phone_number"))
    op.drop_table("support_request")
    op.drop_table("messaging_preference")
    op.drop_table("messaging_pin_credential")
