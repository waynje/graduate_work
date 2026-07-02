from clickhouse_driver import Client

from ugc_etl.config import ETLConfig


def _target_table(config: ETLConfig) -> str:
    return f"{config.clickhouse_database}.{config.clickhouse_table}"


def create_client(config: ETLConfig) -> Client:
    return Client(
        host=config.clickhouse_host,
        port=config.clickhouse_port,
        user=config.clickhouse_user,
        password=config.clickhouse_password,
        # Connect to default DB first so ETL can create target database on startup.
        database="default",
        connect_timeout=5,
        send_receive_timeout=30,
    )


def ensure_schema(client: Client, config: ETLConfig) -> None:
    client.execute(f"CREATE DATABASE IF NOT EXISTS {config.clickhouse_database}")
    client.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_target_table(config)}
        (
            event_id UUID,
            session_id String,
            user_id Nullable(String),
            page_url String,
            duration_ms UInt32,
            referrer Nullable(String),
            occurred_at DateTime64(3, 'UTC'),
            ingested_at DateTime64(3, 'UTC'),
            payload String
        )
        ENGINE = ReplacingMergeTree(ingested_at)
        PARTITION BY toYYYYMM(occurred_at)
        ORDER BY (occurred_at, event_id)
        """
    )


def insert_rows(client: Client, config: ETLConfig, rows: list[tuple]) -> None:
    if not rows:
        return
    client.execute(
        f"""
        INSERT INTO {_target_table(config)}
        (
            event_id,
            session_id,
            user_id,
            page_url,
            duration_ms,
            referrer,
            occurred_at,
            ingested_at,
            payload
        )
        VALUES
        """,
        rows,
    )
