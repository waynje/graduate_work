from __future__ import annotations

import atexit

from flask import Flask

from ugc_service.config import Settings, get_settings
from ugc_service.db import init_engine, run_migrations
from ugc_service.observability import init_sentry
from ugc_service.producer import EventProducer
from ugc_service.routes import events_blueprint, ugc_blueprint


def create_app(
    settings: Settings | None = None, producer: EventProducer | None = None
) -> Flask:
    settings = settings or get_settings()
    init_sentry(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        service_name=settings.sentry_service_name,
        with_flask=True,
    )
    app = Flask(__name__)
    app.config.update(
        DEBUG=settings.debug,
        TESTING=settings.testing,
        UGC_API_PORT=settings.ugc_api_port,
        UGC_DATABASE_URL=settings.ugc_database_url,
        UGC_API_TRUSTED_USER_ID_HEADER=settings.ugc_api_trusted_user_id_header,
        UGC_REQUIRE_TRUSTED_USER_ID=settings.ugc_require_trusted_user_id,
    )
    app.extensions["settings"] = settings

    init_engine(settings.ugc_database_url)
    if settings.ugc_run_migrations_on_startup:
        run_migrations(settings.ugc_database_url)

    event_producer = producer or EventProducer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        topic=settings.ugc_kafka_topic,
        max_retries=settings.ugc_kafka_send_max_retries,
        retry_backoff_sec=settings.ugc_kafka_send_retry_backoff_sec,
        send_timeout_sec=settings.ugc_kafka_send_timeout_sec,
        acks=settings.ugc_kafka_producer_acks,
        producer_retries=settings.ugc_kafka_producer_retries,
        linger_ms=settings.ugc_kafka_producer_linger_ms,
        request_timeout_ms=settings.ugc_kafka_producer_request_timeout_ms,
        max_in_flight_requests_per_connection=settings.ugc_kafka_producer_max_in_flight,
    )
    app.extensions["event_producer"] = event_producer
    app.register_blueprint(events_blueprint)
    app.register_blueprint(ugc_blueprint)

    if producer is None:
        atexit.register(event_producer.close)

    return app
