"""Store LinkedIn preferences on the existing shared client record."""
from alembic import op
import sqlalchemy as sa

revision = "f5a7b9c1d3e6"
down_revision = "e4f6a8b0c2d4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clients", sa.Column("linkedin_profile", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("clients", "linkedin_profile")
