from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Boolean, Numeric
from sqlalchemy.orm import declarative_base, relationship
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from uuid import uuid4

Base = declarative_base()


def utcnow() -> datetime:
    """Return an aware UTC timestamp for new durable evidence records."""
    return datetime.now(timezone.utc)


class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)


class Publication(Base):
    __tablename__ = "publications"
    id = Column(Integer, primary_key=True)
    domain = Column(String(256), unique=True, nullable=False, index=True)
    name = Column(String(128))
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class KnowledgeFile(Base):
    __tablename__ = "knowledge_files"
    __table_args__ = (
        UniqueConstraint("client_id", "sha256", name="uq_knowledge_client_sha256"),
    )
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    source_type = Column(String(8), nullable=False, default="file")  # file|note
    filename = Column(String(256))
    mime = Column(String(128))
    bytes_size = Column(Integer)
    sha256 = Column(String(64))
    uploaded_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    text = Column(Text)  # for manual notes


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("knowledge_files.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=False, default=0)


class KnowledgeEmbedding(Base):
    __tablename__ = "knowledge_embeddings"
    id = Column(Integer, primary_key=True)
    chunk_id = Column(Integer, ForeignKey("knowledge_chunks.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    embedding = Column(Vector(dim=768))  # placeholder; adjust to Embedding Gemma dims


class StyleSnippet(Base):
    __tablename__ = "styles"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    label = Column(String(64))
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SampleQuote(Base):
    __tablename__ = "sample_quotes"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    source = Column(String(128))
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Chat(Base):
    __tablename__ = "chats"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    title = Column(String(256))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    role = Column(String(16), nullable=False)  # system|user|assistant
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("client_name", "url", name="uq_articles_client_url"),)
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    publication_id = Column(Integer, ForeignKey("publications.id"), nullable=True, index=True)
    client_name = Column(String(128), nullable=False, index=True)
    url = Column(String(1024), nullable=False)
    final_url = Column(String(1024))
    canonical_url = Column(String(1024))
    domain = Column(String(256), index=True)
    publication = Column(String(128))
    title = Column(String(512))
    author = Column(String(256))
    # Retain the legacy string projection for compatibility. New code should use
    # the structured UTC value and its provenance fields below.
    published_at = Column(String(64))
    published_at_utc = Column(DateTime(timezone=True), nullable=True, index=True)
    published_date_raw = Column(String(256))
    published_date_source = Column(String(64))
    published_date_confidence = Column(String(16))
    published_date_candidates = Column(JSON)
    description = Column(Text)
    body = Column(Text)
    source_sha256 = Column(String(64))
    source_fetched_at = Column(DateTime(timezone=True))
    source_method = Column(String(32))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ArticleSourceRevision(Base):
    """An append-only snapshot of the source evidence used for a report."""

    __tablename__ = "article_source_revisions"
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, index=True)
    requested_url = Column(String(1024), nullable=False)
    final_url = Column(String(1024))
    canonical_url = Column(String(1024))
    domain = Column(String(256), index=True)
    publication = Column(String(128))
    title = Column(String(512))
    author = Column(String(256))
    description = Column(Text)
    body = Column(Text)
    source_sha256 = Column(String(64), index=True)
    fetched_at = Column(DateTime(timezone=True))
    source_method = Column(String(32), nullable=False)
    published_at = Column(DateTime(timezone=True), index=True)
    published_date_raw = Column(String(256))
    published_date_source = Column(String(64))
    published_date_confidence = Column(String(16))
    published_date_candidates = Column(JSON)
    links = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class ArticleEmbedding(Base):
    __tablename__ = "article_embeddings"
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, index=True)
    embedding = Column(Vector(dim=768))


class ArticleSummary(Base):
    __tablename__ = "article_summaries"
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, index=True)
    source_revision_id = Column(
        Integer,
        ForeignKey("article_source_revisions.id"),
        nullable=True,
        index=True,
    )
    markdown = Column(Text, nullable=False)
    sentiment = Column(String(16))  # Positive|Neutral|Negative
    da = Column(String(32))  # Domain Authority (string to avoid strict parsing)
    muv = Column(String(32))  # Monthly Unique Visitors
    subject = Column(String(256))
    metrics = Column(JSON)
    validation_status = Column(String(32), nullable=False, default="source_verified")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PublicationMetricSnapshot(Base):
    __tablename__ = "publication_metric_snapshots"
    id = Column(Integer, primary_key=True)
    publication_id = Column(Integer, ForeignKey("publications.id"), nullable=False, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=True, index=True)
    source_revision_id = Column(
        Integer,
        ForeignKey("article_source_revisions.id"),
        nullable=True,
        index=True,
    )
    metric_key = Column(String(64), nullable=False, index=True)
    label = Column(String(128))
    value_text = Column(String(128))
    value_numeric = Column(Numeric)
    unit = Column(String(64))
    provider = Column(String(128), nullable=False)
    method = Column(Text)
    confidence = Column(String(16))
    estimated = Column(Boolean, nullable=False, default=False)
    observed_at = Column(DateTime(timezone=True), index=True)
    raw = Column(JSON)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class EvidenceArtifact(Base):
    __tablename__ = "evidence_artifacts"
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, index=True)
    source_revision_id = Column(
        Integer,
        ForeignKey("article_source_revisions.id"),
        nullable=True,
        index=True,
    )
    kind = Column(String(32), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="pending", index=True)
    storage_key = Column(String(1024))
    sha256 = Column(String(64), index=True)
    mime_type = Column(String(128), nullable=False, default="image/png")
    byte_size = Column(Integer)
    captured_at = Column(DateTime(timezone=True), index=True)
    source_url = Column(String(1024), nullable=False)
    final_url = Column(String(1024))
    viewport = Column(JSON)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class CoverageScoreSnapshot(Base):
    __tablename__ = "coverage_score_snapshots"
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, index=True)
    source_revision_id = Column(
        Integer,
        ForeignKey("article_source_revisions.id"),
        nullable=True,
        index=True,
    )
    methodology_version = Column(String(64), nullable=False, index=True)
    formula_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, index=True)
    total_score = Column(Numeric(7, 2))
    components = Column(JSON, nullable=False)
    inputs = Column(JSON, nullable=False)
    calculated_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


# Coverage Tracker models
class Quote(Base):
    __tablename__ = "quotes"
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    sheet_row_id = Column(Text, unique=True)
    client_name = Column(Text, nullable=False, index=True)
    quote_text = Column(Text, nullable=False)
    state = Column(String(32), nullable=False, default="ACTIVE_HOURLY")
    added_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    first_hit_at = Column(DateTime(timezone=True))
    last_hit_at = Column(DateTime(timezone=True))
    last_checked_at = Column(DateTime(timezone=True))
    next_run_at = Column(DateTime(timezone=True))
    hit_count = Column(Integer, default=0)
    days_without_hit = Column(Integer, default=0)
    quote_emb = Column(Vector(dim=768))


class Hit(Base):
    __tablename__ = "hits"
    __table_args__ = (UniqueConstraint("quote_id", "url", name="uq_hits_quote_url"),)
    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid4)
    quote_id = Column(PG_UUID(as_uuid=True), ForeignKey("quotes.id"), index=True)
    client_name = Column(Text)
    url = Column(String(1024))
    domain = Column(String(256), index=True)
    title = Column(String(512))
    snippet = Column(Text)
    published_at = Column(DateTime(timezone=True))
    match_type = Column(String(16))  # exact|partial|paraphrase
    confidence = Column(Numeric)
    markdown = Column(Text)
    source_verified = Column(Boolean, nullable=False, default=False)
    source_sha256 = Column(String(64))
    email_delivery_status = Column(String(16), nullable=False, default="pending")
    email_attempted_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    emailed_at = Column(DateTime(timezone=True))


class HitRead(Base):
    __tablename__ = "hit_reads"
    hit_id = Column(PG_UUID(as_uuid=True), ForeignKey("hits.id"), primary_key=True)
    user_id = Column(PG_UUID(as_uuid=True), primary_key=True)
    read_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)


class AppSettings(Base):
    __tablename__ = "app_settings"
    id = Column(Boolean, primary_key=True, default=True)
    emails = Column(Text)
    email_enabled = Column(Boolean, default=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
