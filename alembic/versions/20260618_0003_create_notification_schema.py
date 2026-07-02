"""create notification schema

Revision ID: 20260618_0003
Revises: 20260605_0002
Create Date: 2026-06-18 01:20:00
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260618_0003"
down_revision = "20260605_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_templates (
            id VARCHAR(64) PRIMARY KEY,
            channel VARCHAR(32) NOT NULL,
            subject_template VARCHAR(255) NOT NULL,
            body_template TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_templates_channel ON notification_templates (channel);")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_campaigns (
            id VARCHAR(36) PRIMARY KEY,
            created_by VARCHAR(64) NOT NULL,
            title VARCHAR(255) NOT NULL,
            template_id VARCHAR(64) NOT NULL,
            recipient_user_ids JSONB NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            scheduled_for TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_campaigns_template_id ON notification_campaigns (template_id);")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_requests (
            id VARCHAR(36) PRIMARY KEY,
            source_type VARCHAR(32) NOT NULL,
            template_id VARCHAR(64) NOT NULL,
            recipient_user_ids JSONB NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            dedup_key VARCHAR(128) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_error TEXT NULL,
            campaign_id VARCHAR(36) NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_notification_requests_dedup_key UNIQUE (dedup_key)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_requests_source_type ON notification_requests (source_type);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_requests_template_id ON notification_requests (template_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_requests_status ON notification_requests (status);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notification_requests_next_attempt_at ON notification_requests (next_attempt_at);"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_requests_campaign_id ON notification_requests (campaign_id);")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_deliveries (
            id VARCHAR(36) PRIMARY KEY,
            request_id VARCHAR(36) NOT NULL,
            user_id VARCHAR(64) NOT NULL,
            channel VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL,
            subject VARCHAR(255) NOT NULL,
            body TEXT NOT NULL,
            provider_message_id VARCHAR(128) NULL,
            error TEXT NULL,
            sent_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_notification_deliveries_request_user_channel UNIQUE (request_id, user_id, channel)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_deliveries_request_id ON notification_deliveries (request_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_deliveries_user_id ON notification_deliveries (user_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_deliveries_channel ON notification_deliveries (channel);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notification_deliveries_status ON notification_deliveries (status);")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_notification_preferences (
            id BIGSERIAL PRIMARY KEY,
            user_id VARCHAR(64) NOT NULL,
            channel VARCHAR(32) NOT NULL DEFAULT 'email',
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_user_notification_preferences_user_channel UNIQUE (user_id, channel)
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_notification_preferences_user_id ON user_notification_preferences (user_id);"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS automatic_notification_rules (
            id VARCHAR(36) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            template_id VARCHAR(64) NOT NULL,
            interval_minutes INTEGER NOT NULL,
            recipient_user_ids JSONB NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            next_run_at TIMESTAMPTZ NOT NULL,
            last_run_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_automatic_notification_rules_next_run_at ON automatic_notification_rules (next_run_at);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS automatic_notification_rules;")
    op.execute("DROP TABLE IF EXISTS user_notification_preferences;")
    op.execute("DROP TABLE IF EXISTS notification_deliveries;")
    op.execute("DROP TABLE IF EXISTS notification_requests;")
    op.execute("DROP TABLE IF EXISTS notification_campaigns;")
    op.execute("DROP TABLE IF EXISTS notification_templates;")
