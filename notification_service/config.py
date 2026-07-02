from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_bootstrap_servers(raw_value: str) -> list[str]:
    servers = [item.strip() for item in raw_value.split(",") if item.strip()]
    if not servers:
        raise ValueError("NOTIFY_KAFKA_BOOTSTRAP_SERVERS must not be empty.")
    return servers


class NotificationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )

    notify_api_port: int = Field(8010, alias="NOTIFY_API_PORT")
    notify_database_url: str = Field(
        "postgresql+psycopg://postgres:postgres@movies-db:5432/movies",
        alias="NOTIFY_DATABASE_URL",
    )
    notify_run_migrations_on_startup: bool = Field(True, alias="NOTIFY_RUN_MIGRATIONS_ON_STARTUP")
    notify_kafka_bootstrap_servers_raw: str = Field(
        "kafka-0:9092,kafka-1:9092,kafka-2:9092",
        alias="NOTIFY_KAFKA_BOOTSTRAP_SERVERS",
    )
    notify_kafka_topic: str = Field("notifications.dispatch", alias="NOTIFY_KAFKA_TOPIC")
    notify_kafka_group_id: str = Field("notifications-worker", alias="NOTIFY_KAFKA_GROUP_ID")
    notify_worker_poll_interval_sec: float = Field(2.0, alias="NOTIFY_WORKER_POLL_INTERVAL_SEC")
    notify_worker_batch_size: int = Field(200, alias="NOTIFY_WORKER_BATCH_SIZE")
    notify_worker_max_attempts: int = Field(5, alias="NOTIFY_WORKER_MAX_ATTEMPTS")
    notify_websocket_poll_interval_sec: float = Field(2.0, alias="NOTIFY_WEBSOCKET_POLL_INTERVAL_SEC")
    notify_scheduler_poll_interval_sec: float = Field(15.0, alias="NOTIFY_SCHEDULER_POLL_INTERVAL_SEC")
    notify_sender_mode: str = Field("log", alias="NOTIFY_SENDER_MODE")
    notify_default_sender_email: str = Field("noreply@movies.local", alias="NOTIFY_DEFAULT_SENDER_EMAIL")
    notify_admin_api_token: str = Field("manager-secret", alias="NOTIFY_ADMIN_API_TOKEN")
    notify_websocket_api_token: str = Field("ws-secret", alias="NOTIFY_WEBSOCKET_API_TOKEN")
    notify_auth_userinfo_url_template: str = Field(
        "http://fastapi:8000/api/v1/auth/users/{user_id}",
        alias="NOTIFY_AUTH_USERINFO_URL_TEMPLATE",
    )
    notify_auth_request_timeout_sec: float = Field(2.0, alias="NOTIFY_AUTH_REQUEST_TIMEOUT_SEC")
    notify_shortlink_base_url: str = Field("http://shortlink-api:8020", alias="NOTIFY_SHORTLINK_BASE_URL")
    notify_sentry_dsn: str | None = Field(None, alias="NOTIFY_SENTRY_DSN")
    notify_sentry_environment: str = Field("development", alias="NOTIFY_SENTRY_ENVIRONMENT")

    @property
    def notify_kafka_bootstrap_servers(self) -> list[str]:
        return parse_bootstrap_servers(self.notify_kafka_bootstrap_servers_raw)


@lru_cache(maxsize=1)
def get_notification_settings() -> NotificationSettings:
    return NotificationSettings()
