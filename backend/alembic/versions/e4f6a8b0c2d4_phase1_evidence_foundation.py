"""Add durable publication, source-revision, evidence, metric, and score records.

Revision ID: e4f6a8b0c2d4
Revises: c3e5f7a9b1d2
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e4f6a8b0c2d4"
down_revision = "c3e5f7a9b1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "publications",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("domain", sa.String(length=256), nullable=False),
        sa.Column("name", sa.String(length=128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("domain", name="uq_publications_domain"),
    )
    op.create_index("ix_publications_domain", "publications", ["domain"], unique=True)

    op.add_column("articles", sa.Column("client_id", sa.Integer(), nullable=True))
    op.add_column("articles", sa.Column("publication_id", sa.Integer(), nullable=True))
    op.add_column("articles", sa.Column("published_at_utc", sa.DateTime(timezone=True), nullable=True))
    op.add_column("articles", sa.Column("published_date_raw", sa.String(length=256), nullable=True))
    op.add_column("articles", sa.Column("published_date_source", sa.String(length=64), nullable=True))
    op.add_column("articles", sa.Column("published_date_confidence", sa.String(length=16), nullable=True))
    op.add_column(
        "articles",
        sa.Column("published_date_candidates", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_foreign_key("fk_articles_client_id", "articles", "clients", ["client_id"], ["id"])
    op.create_foreign_key(
        "fk_articles_publication_id", "articles", "publications", ["publication_id"], ["id"]
    )
    op.create_index("ix_articles_client_id", "articles", ["client_id"], unique=False)
    op.create_index("ix_articles_publication_id", "articles", ["publication_id"], unique=False)
    op.create_index("ix_articles_published_at_utc", "articles", ["published_at_utc"], unique=False)

    # Normalize the currently stored outlet domains into canonical publication
    # records. Client IDs are populated only where the legacy display name has
    # an exact case-insensitive match; unresolved legacy names remain nullable.
    op.execute(
        """
        INSERT INTO publications (domain, name, created_at, updated_at)
        SELECT normalized_domain,
               max(NULLIF(btrim(publication), '')),
               now(),
               now()
        FROM (
            SELECT lower(regexp_replace(btrim(domain), '^www\\.', '', 'i')) AS normalized_domain,
                   publication
            FROM articles
            WHERE domain IS NOT NULL AND btrim(domain) <> ''
        ) AS legacy_publications
        GROUP BY normalized_domain
        ON CONFLICT (domain) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE articles AS article
        SET publication_id = publication.id
        FROM publications AS publication
        WHERE publication.domain = lower(regexp_replace(btrim(article.domain), '^www\\.', '', 'i'))
          AND article.publication_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE articles AS article
        SET client_id = matching_client.id
        FROM (
            SELECT lower(btrim(name)) AS normalized_name, min(id) AS id
            FROM clients
            GROUP BY lower(btrim(name))
        ) AS matching_client
        WHERE lower(btrim(article.client_name)) = matching_client.normalized_name
          AND article.client_id IS NULL
        """
    )

    op.create_table(
        "article_source_revisions",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column("requested_url", sa.String(length=1024), nullable=False),
        sa.Column("final_url", sa.String(length=1024)),
        sa.Column("canonical_url", sa.String(length=1024)),
        sa.Column("domain", sa.String(length=256)),
        sa.Column("publication", sa.String(length=128)),
        sa.Column("title", sa.String(length=512)),
        sa.Column("author", sa.String(length=256)),
        sa.Column("description", sa.Text()),
        sa.Column("body", sa.Text()),
        sa.Column("source_sha256", sa.String(length=64)),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
        sa.Column("source_method", sa.String(length=32), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("published_date_raw", sa.String(length=256)),
        sa.Column("published_date_source", sa.String(length=64)),
        sa.Column("published_date_confidence", sa.String(length=16)),
        sa.Column("published_date_candidates", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("links", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_article_source_revisions_article_id", "article_source_revisions", ["article_id"])
    op.create_index("ix_article_source_revisions_domain", "article_source_revisions", ["domain"])
    op.create_index("ix_article_source_revisions_source_sha256", "article_source_revisions", ["source_sha256"])
    op.create_index("ix_article_source_revisions_published_at", "article_source_revisions", ["published_at"])

    op.add_column("article_summaries", sa.Column("source_revision_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_article_summaries_source_revision_id",
        "article_summaries",
        "article_source_revisions",
        ["source_revision_id"],
        ["id"],
    )
    op.create_index(
        "ix_article_summaries_source_revision_id",
        "article_summaries",
        ["source_revision_id"],
        unique=False,
    )

    op.create_table(
        "publication_metric_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("publication_id", sa.Integer(), sa.ForeignKey("publications.id"), nullable=False),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=True),
        sa.Column(
            "source_revision_id",
            sa.Integer(),
            sa.ForeignKey("article_source_revisions.id"),
            nullable=True,
        ),
        sa.Column("metric_key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128)),
        sa.Column("value_text", sa.String(length=128)),
        sa.Column("value_numeric", sa.Numeric()),
        sa.Column("unit", sa.String(length=64)),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("method", sa.Text()),
        sa.Column("confidence", sa.String(length=16)),
        sa.Column("estimated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_publication_metric_snapshots_publication_id", "publication_metric_snapshots", ["publication_id"])
    op.create_index("ix_publication_metric_snapshots_article_id", "publication_metric_snapshots", ["article_id"])
    op.create_index(
        "ix_publication_metric_snapshots_source_revision_id",
        "publication_metric_snapshots",
        ["source_revision_id"],
    )
    op.create_index("ix_publication_metric_snapshots_metric_key", "publication_metric_snapshots", ["metric_key"])
    op.create_index("ix_publication_metric_snapshots_observed_at", "publication_metric_snapshots", ["observed_at"])

    op.create_table(
        "evidence_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column(
            "source_revision_id",
            sa.Integer(),
            sa.ForeignKey("article_source_revisions.id"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("storage_key", sa.String(length=1024)),
        sa.Column("sha256", sa.String(length=64)),
        sa.Column("mime_type", sa.String(length=128), nullable=False, server_default="image/png"),
        sa.Column("byte_size", sa.Integer()),
        sa.Column("captured_at", sa.DateTime(timezone=True)),
        sa.Column("source_url", sa.String(length=1024), nullable=False),
        sa.Column("final_url", sa.String(length=1024)),
        sa.Column("viewport", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_evidence_artifacts_article_id", "evidence_artifacts", ["article_id"])
    op.create_index("ix_evidence_artifacts_source_revision_id", "evidence_artifacts", ["source_revision_id"])
    op.create_index("ix_evidence_artifacts_kind", "evidence_artifacts", ["kind"])
    op.create_index("ix_evidence_artifacts_status", "evidence_artifacts", ["status"])
    op.create_index("ix_evidence_artifacts_sha256", "evidence_artifacts", ["sha256"])
    op.create_index("ix_evidence_artifacts_captured_at", "evidence_artifacts", ["captured_at"])

    op.create_table(
        "coverage_score_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id"), nullable=False),
        sa.Column(
            "source_revision_id",
            sa.Integer(),
            sa.ForeignKey("article_source_revisions.id"),
            nullable=True,
        ),
        sa.Column("methodology_version", sa.String(length=64), nullable=False),
        sa.Column("formula_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("total_score", sa.Numeric(precision=7, scale=2)),
        sa.Column("components", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_coverage_score_snapshots_article_id", "coverage_score_snapshots", ["article_id"])
    op.create_index("ix_coverage_score_snapshots_source_revision_id", "coverage_score_snapshots", ["source_revision_id"])
    op.create_index("ix_coverage_score_snapshots_methodology_version", "coverage_score_snapshots", ["methodology_version"])
    op.create_index("ix_coverage_score_snapshots_status", "coverage_score_snapshots", ["status"])
    op.create_index("ix_coverage_score_snapshots_calculated_at", "coverage_score_snapshots", ["calculated_at"])


def downgrade() -> None:
    op.drop_table("coverage_score_snapshots")
    op.drop_table("evidence_artifacts")
    op.drop_table("publication_metric_snapshots")

    op.drop_index("ix_article_summaries_source_revision_id", table_name="article_summaries")
    op.drop_constraint(
        "fk_article_summaries_source_revision_id", "article_summaries", type_="foreignkey"
    )
    op.drop_column("article_summaries", "source_revision_id")

    op.drop_table("article_source_revisions")

    op.drop_index("ix_articles_published_at_utc", table_name="articles")
    op.drop_index("ix_articles_publication_id", table_name="articles")
    op.drop_index("ix_articles_client_id", table_name="articles")
    op.drop_constraint("fk_articles_publication_id", "articles", type_="foreignkey")
    op.drop_constraint("fk_articles_client_id", "articles", type_="foreignkey")
    op.drop_column("articles", "published_date_candidates")
    op.drop_column("articles", "published_date_confidence")
    op.drop_column("articles", "published_date_source")
    op.drop_column("articles", "published_date_raw")
    op.drop_column("articles", "published_at_utc")
    op.drop_column("articles", "publication_id")
    op.drop_column("articles", "client_id")

    op.drop_index("ix_publications_domain", table_name="publications")
    op.drop_table("publications")
