"""init schema

Revision ID: 22b9d04b2de1
Revises: 0001_vector
Create Date: 2025-09-18

"""
from alembic import op
import sqlalchemy as sa
import pgvector

# revision identifiers, used by Alembic.
revision = "22b9d04b2de1"
down_revision = "0001_vector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
    )
    op.create_index(op.f("ix_clients_slug"), "clients", ["slug"], unique=True)

    op.create_table(
        "chats",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("title", sa.String(length=256)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(op.f("ix_chats_client_id"), "chats", ["client_id"], unique=False)

    op.create_table(
        "knowledge_files",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("source_type", sa.String(length=8), nullable=False),
        sa.Column("filename", sa.String(length=256)),
        sa.Column("mime", sa.String(length=128)),
        sa.Column("bytes_size", sa.Integer()),
        sa.Column("sha256", sa.String(length=64)),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.Column("text", sa.Text()),
    )
    op.create_index(op.f("ix_knowledge_files_client_id"), "knowledge_files", ["client_id"], unique=False)
    op.create_unique_constraint("uq_knowledge_client_sha256", "knowledge_files", ["client_id", "sha256"]) 

    op.create_table(
        "sample_quotes",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("source", sa.String(length=128)),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(op.f("ix_sample_quotes_client_id"), "sample_quotes", ["client_id"], unique=False)

    op.create_table(
        "styles",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("label", sa.String(length=64)),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(op.f("ix_styles_client_id"), "styles", ["client_id"], unique=False)

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("chat_id", sa.Integer(), sa.ForeignKey("chats.id"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(op.f("ix_chat_messages_chat_id"), "chat_messages", ["chat_id"], unique=False)
    op.create_index(op.f("ix_chat_messages_client_id"), "chat_messages", ["client_id"], unique=False)

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("file_id", sa.Integer(), sa.ForeignKey("knowledge_files.id"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
    )
    op.create_index(op.f("ix_knowledge_chunks_client_id"), "knowledge_chunks", ["client_id"], unique=False)
    op.create_index(op.f("ix_knowledge_chunks_file_id"), "knowledge_chunks", ["file_id"], unique=False)

    op.create_table(
        "knowledge_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("chunk_id", sa.Integer(), sa.ForeignKey("knowledge_chunks.id"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=768)),
    )
    op.create_index(op.f("ix_knowledge_embeddings_chunk_id"), "knowledge_embeddings", ["chunk_id"], unique=False)
    op.create_index(op.f("ix_knowledge_embeddings_client_id"), "knowledge_embeddings", ["client_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_knowledge_embeddings_client_id"), table_name="knowledge_embeddings")
    op.drop_index(op.f("ix_knowledge_embeddings_chunk_id"), table_name="knowledge_embeddings")
    op.drop_table("knowledge_embeddings")

    op.drop_index(op.f("ix_knowledge_chunks_file_id"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_client_id"), table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")

    op.drop_index(op.f("ix_chat_messages_client_id"), table_name="chat_messages")
    op.drop_index(op.f("ix_chat_messages_chat_id"), table_name="chat_messages")
    op.drop_table("chat_messages")

    op.drop_index(op.f("ix_styles_client_id"), table_name="styles")
    op.drop_table("styles")

    op.drop_index(op.f("ix_sample_quotes_client_id"), table_name="sample_quotes")
    op.drop_table("sample_quotes")

    op.drop_index(op.f("ix_knowledge_files_client_id"), table_name="knowledge_files")
    op.drop_table("knowledge_files")

    op.drop_index(op.f("ix_chats_client_id"), table_name="chats")
    op.drop_table("chats")

    op.drop_index(op.f("ix_clients_slug"), table_name="clients")
    op.drop_table("clients")
