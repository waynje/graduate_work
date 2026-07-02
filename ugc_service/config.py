from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def parse_bootstrap_servers(raw_value: str) -> list[str]:
    servers = [server.strip() for server in raw_value.split(",") if server.strip()]
    if not servers:
        raise ValueError("KAFKA_BOOTSTRAP_SERVERS must contain at least one server.")
    return servers


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        populate_by_name=True,
    )

    testing: bool = False
    debug: bool = Field(False, alias="UGC_DEBUG")
    ugc_api_port: int = Field(8001, alias="UGC_API_PORT")
    kafka_bootstrap_servers: list[str] = Field(
        default_factory=lambda: ["kafka-0:9092", "kafka-1:9092", "kafka-2:9092"],
        alias="KAFKA_BOOTSTRAP_SERVERS",
    )
    ugc_kafka_topic: str = Field("ugc.events.raw", alias="UGC_KAFKA_TOPIC")
    ugc_kafka_group_id: str = Field("ugc-events-consumer", alias="UGC_KAFKA_GROUP_ID")
    ugc_kafka_send_max_retries: int = Field(2, alias="UGC_KAFKA_SEND_MAX_RETRIES")
    ugc_kafka_send_retry_backoff_sec: float = Field(0.2, alias="UGC_KAFKA_SEND_RETRY_BACKOFF_SEC")
    ugc_kafka_send_timeout_sec: float = Field(2.0, alias="UGC_KAFKA_SEND_TIMEOUT_SEC")
    ugc_kafka_producer_acks: str = Field("all", alias="UGC_KAFKA_PRODUCER_ACKS")
    ugc_kafka_producer_retries: int = Field(2, alias="UGC_KAFKA_PRODUCER_RETRIES")
    ugc_kafka_producer_linger_ms: int = Field(5, alias="UGC_KAFKA_PRODUCER_LINGER_MS")
    ugc_kafka_producer_request_timeout_ms: int = Field(
        5000, alias="UGC_KAFKA_PRODUCER_REQUEST_TIMEOUT_MS"
    )
    ugc_kafka_producer_max_in_flight: int = Field(1, alias="UGC_KAFKA_PRODUCER_MAX_IN_FLIGHT")
    ugc_kafka_consumer_reconnect_backoff_sec: float = Field(
        3.0, alias="UGC_KAFKA_CONSUMER_RECONNECT_BACKOFF_SEC"
    )
    ugc_kafka_consumer_processing_backoff_sec: float = Field(
        1.0, alias="UGC_KAFKA_CONSUMER_PROCESSING_BACKOFF_SEC"
    )
    ugc_api_trusted_user_id_header: str = Field("X-User-Id", alias="UGC_API_TRUSTED_USER_ID_HEADER")
    ugc_require_trusted_user_id: bool = Field(True, alias="UGC_REQUIRE_TRUSTED_USER_ID")
    ugc_run_migrations_on_startup: bool = Field(False, alias="UGC_RUN_MIGRATIONS_ON_STARTUP")
    ugc_database_url: str = Field(
        "postgresql+psycopg://postgres:postgres@movies-db:5432/movies",
        alias="UGC_DATABASE_URL",
    )
    sentry_dsn: str | None = Field(None, alias="SENTRY_DSN")
    sentry_environment: str = Field("development", alias="SENTRY_ENVIRONMENT")
    sentry_traces_sample_rate: float = Field(0.0, alias="SENTRY_TRACES_SAMPLE_RATE")
    sentry_service_name: str = Field("ugc-service", alias="SENTRY_SERVICE_NAME")

    @field_validator("kafka_bootstrap_servers", mode="before")
    @classmethod
    def _validate_bootstrap_servers(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, list):
            parsed = [server.strip() for server in value if server.strip()]
            if not parsed:
                raise ValueError("KAFKA_BOOTSTRAP_SERVERS must contain at least one server.")
            return parsed
        return parse_bootstrap_servers(value)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
