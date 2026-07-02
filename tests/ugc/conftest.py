from pathlib import Path

import pytest

from ugc_service.app import create_app
from ugc_service.config import Settings
from ugc_service.db import create_tables, init_engine


class FakeProducer:
    def __init__(self):
        self.messages = []

    def send(self, payload: dict) -> None:
        self.messages.append(payload)

    def close(self) -> None:
        return None


@pytest.fixture()
def fake_producer():
    return FakeProducer()


@pytest.fixture()
def app(fake_producer):
    settings = Settings(
        testing=True,
        ugc_database_url="sqlite+pysqlite:///./ugc_test.db",
        kafka_bootstrap_servers=["localhost:9092"],
        ugc_kafka_send_max_retries=1,
        ugc_kafka_send_retry_backoff_sec=0.01,
        ugc_kafka_consumer_reconnect_backoff_sec=0.01,
        ugc_kafka_consumer_processing_backoff_sec=0.01,
        ugc_require_trusted_user_id=True,
        ugc_run_migrations_on_startup=False,
    )
    app = create_app(settings=settings, producer=fake_producer)
    return app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def clear_events():
    db_path = Path("ugc_test.db")
    if db_path.exists():
        db_path.unlink()
    init_engine("sqlite+pysqlite:///./ugc_test.db")
    create_tables()
