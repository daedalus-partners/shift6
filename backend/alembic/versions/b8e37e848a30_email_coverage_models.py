from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


revision = 'b8e37e848a30'
down_revision = '22b9d04b2de1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'articles',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('client_name', sa.String(length=128), nullable=False),
        sa.Column('url', sa.String(length=1024), nullable=False, unique=True),
        sa.Column('domain', sa.String(length=256)),
        sa.Column('title', sa.String(length=512)),
        sa.Column('author', sa.String(length=256)),
        sa.Column('published_at', sa.String(length=64)),
        sa.Column('description', sa.Text()),
        sa.Column('body', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_articles_client_name', 'articles', ['client_name'])
    op.create_index('ix_articles_domain', 'articles', ['domain'])

    op.create_table(
        'article_embeddings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('article_id', sa.Integer(), sa.ForeignKey('articles.id'), nullable=False),
        sa.Column('embedding', pgvector.sqlalchemy.Vector(dim=768)),
    )
    op.create_index('ix_article_embeddings_article_id', 'article_embeddings', ['article_id'])

    op.create_table(
        'article_summaries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('article_id', sa.Integer(), sa.ForeignKey('articles.id'), nullable=False),
        sa.Column('markdown', sa.Text(), nullable=False),
        sa.Column('sentiment', sa.String(length=16)),
        sa.Column('da', sa.String(length=32)),
        sa.Column('muv', sa.String(length=32)),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_article_summaries_article_id', 'article_summaries', ['article_id'])


def downgrade() -> None:
    op.drop_index('ix_article_summaries_article_id', table_name='article_summaries')
    op.drop_table('article_summaries')
    op.drop_index('ix_article_embeddings_article_id', table_name='article_embeddings')
    op.drop_table('article_embeddings')
    op.drop_index('ix_articles_domain', table_name='articles')
    op.drop_index('ix_articles_client_name', table_name='articles')
    op.drop_table('articles')


