"""Store deterministic coverage-email subjects.

Revision ID: f1c2d3e4a5b6
Revises: ee2a4b8bb0cd
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa


revision = "f1c2d3e4a5b6"
down_revision = "ee2a4b8bb0cd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("article_summaries", sa.Column("subject", sa.String(length=256), nullable=True))


def downgrade() -> None:
    op.drop_column("article_summaries", "subject")
