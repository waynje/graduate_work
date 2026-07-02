"""create auth schema

Revision ID: 20260423_0001
Revises:
Create Date: 2026-04-23 00:00:00
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260423_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_users (
            id UUID PRIMARY KEY,
            login VARCHAR(255) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_superuser BOOLEAN NOT NULL DEFAULT FALSE,
            token_version INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_roles (
            id UUID PRIMARY KEY,
            name VARCHAR(255) UNIQUE NOT NULL,
            description TEXT NOT NULL DEFAULT ''
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_user_roles (
            user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
            role_id UUID NOT NULL REFERENCES auth_roles(id) ON DELETE CASCADE,
            PRIMARY KEY (user_id, role_id)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_refresh_tokens (
            jti UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked BOOLEAN NOT NULL DEFAULT FALSE,
            user_agent TEXT,
            ip TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_login_history (
            id BIGSERIAL PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
            user_agent TEXT,
            ip TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_social_accounts (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
            provider VARCHAR(64) NOT NULL,
            social_id VARCHAR(255) NOT NULL,
            email VARCHAR(255),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(provider, social_id),
            UNIQUE(provider, user_id)
        );
        """
    )
    op.execute(
        """
        INSERT INTO auth_roles (id, name, description)
        VALUES ('00000000-0000-0000-0000-000000000001', 'user', 'Default user role')
        ON CONFLICT (name) DO NOTHING;
        """
    )
    op.execute(
        """
        INSERT INTO auth_roles (id, name, description)
        VALUES ('00000000-0000-0000-0000-000000000002', 'admin', 'Administrative role')
        ON CONFLICT (name) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_social_accounts;")
    op.execute("DROP TABLE IF EXISTS auth_login_history;")
    op.execute("DROP TABLE IF EXISTS auth_refresh_tokens;")
    op.execute("DROP TABLE IF EXISTS auth_user_roles;")
    op.execute("DROP TABLE IF EXISTS auth_roles;")
    op.execute("DROP TABLE IF EXISTS auth_users;")
