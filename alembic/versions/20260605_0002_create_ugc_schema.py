"""create ugc schema tables

Revision ID: 20260605_0002
Revises: 20260423_0001
Create Date: 2026-06-05 16:40:00
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260605_0002"
down_revision = "20260423_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ugc_events (
            id VARCHAR(36) PRIMARY KEY,
            event_type VARCHAR(32) NOT NULL,
            event_name VARCHAR(64) NOT NULL,
            user_id VARCHAR(64),
            session_id VARCHAR(64) NOT NULL,
            page_url TEXT,
            duration_ms INTEGER,
            occurred_at TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_ugc_events_event_type ON ugc_events (event_type);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ugc_events_event_name ON ugc_events (event_name);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ugc_events_user_id ON ugc_events (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ugc_events_session_id ON ugc_events (session_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ugc_events_occurred_at ON ugc_events (occurred_at);")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS ugc_rejected_events (
            id VARCHAR(36) PRIMARY KEY,
            reason VARCHAR(256) NOT NULL,
            payload JSONB NOT NULL,
            source_topic VARCHAR(128),
            source_partition INTEGER,
            source_offset BIGINT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ugc_rejected_events_source_topic ON ugc_rejected_events (source_topic);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ugc_rejected_events_source_partition ON ugc_rejected_events (source_partition);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ugc_rejected_events_source_offset ON ugc_rejected_events (source_offset);"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS movie_ratings (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL,
            movie_id VARCHAR(64) NOT NULL,
            score SMALLINT NOT NULL CHECK (score >= 0 AND score <= 10),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_movie_ratings_user_movie UNIQUE (user_id, movie_id)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_movie_ratings_user_id ON movie_ratings (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_movie_ratings_movie_id ON movie_ratings (movie_id);")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS movie_reviews (
            id VARCHAR(36) PRIMARY KEY,
            movie_id VARCHAR(64) NOT NULL,
            user_id VARCHAR(64) NOT NULL,
            review_text TEXT NOT NULL,
            movie_score SMALLINT CHECK (movie_score IS NULL OR (movie_score >= 0 AND movie_score <= 10)),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_movie_reviews_movie_id ON movie_reviews (movie_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_movie_reviews_user_id ON movie_reviews (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_movie_reviews_created_at ON movie_reviews (created_at);")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS review_votes (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL,
            review_id VARCHAR(36) NOT NULL REFERENCES movie_reviews(id) ON DELETE CASCADE,
            vote SMALLINT NOT NULL CHECK (vote IN (-1, 1)),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_review_votes_user_review UNIQUE (user_id, review_id)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_review_votes_user_id ON review_votes (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_review_votes_review_id ON review_votes (review_id);")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_bookmarks (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL,
            movie_id VARCHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_user_bookmarks_user_movie UNIQUE (user_id, movie_id)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_bookmarks_user_id ON user_bookmarks (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_bookmarks_movie_id ON user_bookmarks (movie_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_bookmarks_created_at ON user_bookmarks (created_at);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_bookmarks;")
    op.execute("DROP TABLE IF EXISTS review_votes;")
    op.execute("DROP TABLE IF EXISTS movie_reviews;")
    op.execute("DROP TABLE IF EXISTS movie_ratings;")
    op.execute("DROP TABLE IF EXISTS ugc_rejected_events;")
    op.execute("DROP TABLE IF EXISTS ugc_events;")
