"""enable vector extension

Revision ID: 0001_vector
Revises: 
Create Date: 2025-09-18

"""
from alembic import op
import sqlalchemy as sa  # noqa: F401

# revision identifiers, used by Alembic.
revision = "0001_vector"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Intentionally do not drop the extension to avoid breaking dependent objects
    pass
