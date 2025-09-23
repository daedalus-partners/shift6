from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship
from pgvector.sqlalchemy import Vector

Base = declarative_base()


class Client(Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True)
    slug = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)


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
    id = Column(Integer, primary_key=True)
    client_name = Column(String(128), nullable=False, index=True)
    url = Column(String(1024), nullable=False, unique=True)
    domain = Column(String(256), index=True)
    title = Column(String(512))
    author = Column(String(256))
    published_at = Column(String(64))
    description = Column(Text)
    body = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ArticleEmbedding(Base):
    __tablename__ = "article_embeddings"
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, index=True)
    embedding = Column(Vector(dim=768))


class ArticleSummary(Base):
    __tablename__ = "article_summaries"
    id = Column(Integer, primary_key=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False, index=True)
    markdown = Column(Text, nullable=False)
    sentiment = Column(String(16))  # Positive|Neutral|Negative
    da = Column(String(32))  # Domain Authority (string to avoid strict parsing)
    muv = Column(String(32))  # Monthly Unique Visitors
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
