import re

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ETLConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    kafka_bootstrap_servers: str = Field(
        default="kafka-0:9092,kafka-1:9092,kafka-2:9092",
        alias="KAFKA_BOOTSTRAP_SERVERS",
    )
    kafka_topic: str = Field(default="ugc.events.raw", alias="UGC_KAFKA_TOPIC")
    kafka_group_id: str = Field(default="ugc-clickhouse-etl", alias="UGC_CLICKHOUSE_ETL_GROUP_ID")
    kafka_poll_timeout_ms: int = Field(default=5000, alias="UGC_ETL_POLL_TIMEOUT_MS")
    kafka_batch_size: int = Field(default=500, alias="UGC_ETL_BATCH_SIZE")

    clickhouse_host: str = Field(default="clickhouse", alias="CLICKHOUSE_HOST")
    clickhouse_port: int = Field(default=9000, alias="CLICKHOUSE_PORT")
    clickhouse_user: str = Field(default="default", alias="CLICKHOUSE_USER")
    clickhouse_password: str = Field(default="clickhouse", alias="CLICKHOUSE_PASSWORD")
    clickhouse_database: str = Field(default="ugc", alias="CLICKHOUSE_DATABASE")
    clickhouse_table: str = Field(default="page_views", alias="CLICKHOUSE_TABLE")

    max_insert_retries: int = Field(default=5, alias="UGC_ETL_INSERT_MAX_RETRIES")
    retry_backoff_sec: float = Field(default=1.0, alias="UGC_ETL_RETRY_BACKOFF_SEC")
    reconnect_backoff_sec: float = Field(default=3.0, alias="UGC_ETL_RECONNECT_BACKOFF_SEC")

    memory_metrics_port: int = Field(default=9108, alias="UGC_ETL_METRICS_PORT")
    memory_metrics_interval_sec: int = Field(default=5, alias="UGC_ETL_MEMORY_METRICS_INTERVAL_SEC")

    @field_validator("clickhouse_database", "clickhouse_table")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not _IDENTIFIER_RE.fullmatch(value):
            raise ValueError("ClickHouse identifiers must match ^[A-Za-z_][A-Za-z0-9_]*$.")
        return value

    @property
    def kafka_bootstrap_server_list(self) -> list[str]:
        servers = [
            server.strip() for server in self.kafka_bootstrap_servers.split(",") if server.strip()
        ]
        if not servers:
            raise ValueError("KAFKA_BOOTSTRAP_SERVERS must contain at least one server.")
        return servers
