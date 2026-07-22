"""Persist verified email source provenance and client isolation.

Revision ID: a2d4e6f8b0c1
Revises: f1c2d3e4a5b6
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "a2d4e6f8b0c1"
down_revision = "f1c2d3e4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("articles_url_key", "articles", type_="unique")
    op.create_unique_constraint("uq_articles_client_url", "articles", ["client_name", "url"])
    op.add_column("articles", sa.Column("final_url", sa.String(length=1024)))
    op.add_column("articles", sa.Column("publication", sa.String(length=128)))
    op.add_column("articles", sa.Column("canonical_url", sa.String(length=1024)))
    op.add_column("articles", sa.Column("source_sha256", sa.String(length=64)))
    op.add_column("articles", sa.Column("source_fetched_at", sa.DateTime(timezone=True)))
    op.add_column("articles", sa.Column("source_method", sa.String(length=32)))
    op.add_column("article_summaries", sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text())))
    op.add_column(
        "article_summaries",
        sa.Column("validation_status", sa.String(length=32), nullable=False, server_default="source_verified"),
    )


def downgrade() -> None:
    op.drop_column("article_summaries", "validation_status")
    op.drop_column("article_summaries", "metrics")
    op.drop_column("articles", "source_method")
    op.drop_column("articles", "source_fetched_at")
    op.drop_column("articles", "source_sha256")
    op.drop_column("articles", "canonical_url")
    op.drop_column("articles", "final_url")
    op.drop_column("articles", "publication")
    op.drop_constraint("uq_articles_client_url", "articles", type_="unique")
    op.create_unique_constraint("articles_url_key", "articles", ["url"])
