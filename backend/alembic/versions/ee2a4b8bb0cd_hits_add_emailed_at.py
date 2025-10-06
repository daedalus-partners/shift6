"""hits add emailed_at

Revision ID: ee2a4b8bb0cd
Revises: d3a1f1c9c2a0
Create Date: 2025-09-23

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "ee2a4b8bb0cd"
down_revision = "d3a1f1c9c2a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hits", sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("hits", "emailed_at")

