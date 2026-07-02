from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone

from kafka import KafkaConsumer, TopicPartition
from kafka.structs import OffsetAndMetadata

from ugc_service.config import Settings, get_settings
from ugc_service.db import init_engine, run_migrations, session_scope
from ugc_service.models import UGCEvent, UGCRejectedEvent
from ugc_service.observability import init_sentry


logger = logging.getLogger(__name__)


def _parse_occurred_at(raw_value: str | None) -> datetime:
    if not raw_value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("occurred_at must be an ISO-8601 datetime.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _store_rejected_event(
    payload: dict,
    reason: str,
    *,
    topic: str | None,
    partition: int | None,
    offset: int | None,
) -> bool:
    try:
        with session_scope() as session:
            session.add(
                UGCRejectedEvent(
                    id=str(uuid.uuid4()),
                    reason=reason,
                    payload=payload,
                    source_topic=topic,
                    source_partition=partition,
                    source_offset=offset,
                )
            )
        logger.warning(
            "Event rejected and stored. reason=%s topic=%s partition=%s offset=%s",
            reason,
            topic,
            partition,
            offset,
        )
        return True
    except Exception as exc:
        logger.exception("Failed to store rejected event: %s", exc)
        return False


def process_event(
    payload: dict,
    *,
    topic: str | None = None,
    partition: int | None = None,
    offset: int | None = None,
) -> bool:
    if not isinstance(payload, dict):
        return _store_rejected_event(
            {"raw_payload": str(payload)},
            "payload must be a JSON object",
            topic=topic,
            partition=partition,
            offset=offset,
        )

    required_fields = {"event_type", "event_name", "session_id"}
    missing_fields = sorted(required_fields.difference(payload.keys()))
    if missing_fields:
        return _store_rejected_event(
            payload,
            f"missing required fields: {', '.join(missing_fields)}",
            topic=topic,
            partition=partition,
            offset=offset,
        )

    try:
        occurred_at = _parse_occurred_at(payload.get("occurred_at"))
    except ValueError as exc:
        return _store_rejected_event(
            payload,
            str(exc),
            topic=topic,
            partition=partition,
            offset=offset,
        )

    event = UGCEvent(
        id=str(uuid.uuid4()),
        event_type=payload["event_type"],
        event_name=payload["event_name"],
        user_id=payload.get("user_id"),
        session_id=payload["session_id"],
        page_url=payload.get("page_url"),
        duration_ms=payload.get("duration_ms"),
        occurred_at=occurred_at,
        payload=payload,
    )
    try:
        with session_scope() as session:
            session.add(event)
        return True
    except Exception as exc:
        logger.exception("Failed to persist event to PostgreSQL: %s", exc)
        return False


def consume_forever(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    init_sentry(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        service_name=settings.sentry_service_name,
        with_flask=False,
    )
    init_engine(settings.ugc_database_url)
    if settings.ugc_run_migrations_on_startup:
        run_migrations(settings.ugc_database_url)

    while True:
        consumer = None
        try:
            consumer = KafkaConsumer(
                settings.ugc_kafka_topic,
                bootstrap_servers=settings.kafka_bootstrap_servers,
                group_id=settings.ugc_kafka_group_id,
                auto_offset_reset="earliest",
                value_deserializer=lambda value: json.loads(value.decode("utf-8")),
                enable_auto_commit=False,
            )
            logger.info("UGC consumer connected to Kafka.")
            for message in consumer:
                topic_partition = TopicPartition(message.topic, message.partition)
                processed = process_event(
                    message.value,
                    topic=message.topic,
                    partition=message.partition,
                    offset=message.offset,
                )
                if processed:
                    consumer.commit(
                        offsets={topic_partition: OffsetAndMetadata(message.offset + 1, None)}
                    )
                    continue

                logger.error(
                    "Event processing failed. Offset not committed. topic=%s partition=%s offset=%s",
                    message.topic,
                    message.partition,
                    message.offset,
                )
                consumer.seek(topic_partition, message.offset)
                time.sleep(settings.ugc_kafka_consumer_processing_backoff_sec)
        except Exception as exc:
            logger.exception(
                "UGC consumer failed to read from Kafka: %s. Retry in %.1fs",
                exc,
                settings.ugc_kafka_consumer_reconnect_backoff_sec,
            )
            time.sleep(settings.ugc_kafka_consumer_reconnect_backoff_sec)
        finally:
            if consumer is not None:
                consumer.close()


if __name__ == "__main__":
    consume_forever()
