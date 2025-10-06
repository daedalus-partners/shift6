"""coverage tables

Revision ID: d3a1f1c9c2a0
Revises: b8e37e848a30
Create Date: 2025-09-23

"""
from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy
from sqlalchemy.dialects import postgresql as psql

# revision identifiers, used by Alembic.
revision = "d3a1f1c9c2a0"
down_revision = "b8e37e848a30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # quotes
    op.create_table(
        "quotes",
        sa.Column("id", psql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("sheet_row_id", sa.Text(), unique=True),
        sa.Column("client_name", sa.Text(), nullable=False),
        sa.Column("quote_text", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="ACTIVE_HOURLY"),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("first_hit_at", sa.DateTime(timezone=True)),
        sa.Column("last_hit_at", sa.DateTime(timezone=True)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("hit_count", sa.Integer(), server_default="0"),
        sa.Column("days_without_hit", sa.Integer(), server_default="0"),
        sa.Column("quote_emb", pgvector.sqlalchemy.Vector(dim=768)),
    )
    op.create_index("ix_quotes_client_name", "quotes", ["client_name"]) 
    op.create_index("ix_quotes_next_run_at", "quotes", ["next_run_at"]) 

    # hits
    op.create_table(
        "hits",
        sa.Column("id", psql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("quote_id", psql.UUID(as_uuid=True), sa.ForeignKey("quotes.id"), nullable=True),
        sa.Column("client_name", sa.Text()),
        sa.Column("url", sa.String(length=1024), unique=True),
        sa.Column("domain", sa.String(length=256)),
        sa.Column("title", sa.String(length=512)),
        sa.Column("snippet", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("match_type", sa.String(length=16)),  # exact|partial|paraphrase
        sa.Column("confidence", sa.Numeric()),
        sa.Column("markdown", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("ix_hits_quote_id", "hits", ["quote_id"]) 
    op.create_index("ix_hits_domain", "hits", ["domain"]) 
    op.create_index("ix_hits_client_name", "hits", ["client_name"]) 
    op.create_index("ix_hits_created_at", "hits", ["created_at"]) 

    # hit_reads
    op.create_table(
        "hit_reads",
        sa.Column("hit_id", psql.UUID(as_uuid=True), sa.ForeignKey("hits.id"), primary_key=True, nullable=False),
        sa.Column("user_id", psql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )

    # app_settings
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Boolean(), primary_key=True, server_default=sa.text("TRUE")),
        sa.Column("emails", sa.Text()),
        sa.Column("email_enabled", sa.Boolean(), server_default=sa.text("FALSE")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_table("hit_reads")
    op.drop_index("ix_hits_created_at", table_name="hits")
    op.drop_index("ix_hits_client_name", table_name="hits")
    op.drop_index("ix_hits_domain", table_name="hits")
    op.drop_index("ix_hits_quote_id", table_name="hits")
    op.drop_table("hits")
    op.drop_index("ix_quotes_next_run_at", table_name="quotes")
    op.drop_index("ix_quotes_client_name", table_name="quotes")
    op.drop_table("quotes")

