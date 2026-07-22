"""Verify coverage sources and make delivery claims durable.

Revision ID: c3e5f7a9b1d2
Revises: a2d4e6f8b0c1
"""

from alembic import op
import sqlalchemy as sa


revision = "c3e5f7a9b1d2"
down_revision = "a2d4e6f8b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("hits_url_key", "hits", type_="unique")
    op.create_unique_constraint("uq_hits_quote_url", "hits", ["quote_id", "url"])
    op.add_column("hits", sa.Column("source_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("hits", sa.Column("source_sha256", sa.String(length=64)))
    op.add_column(
        "hits", sa.Column("email_delivery_status", sa.String(length=16), nullable=False, server_default="pending")
    )
    op.add_column("hits", sa.Column("email_attempted_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("hits", "email_attempted_at")
    op.drop_column("hits", "email_delivery_status")
    op.drop_column("hits", "source_sha256")
    op.drop_column("hits", "source_verified")
    op.drop_constraint("uq_hits_quote_url", "hits", type_="unique")
    op.create_unique_constraint("hits_url_key", "hits", ["url"])
