from __future__ import annotations

import logging
import time
import json

from kafka import KafkaConsumer, TopicPartition
from kafka.structs import OffsetAndMetadata

from ugc_etl.clickhouse import create_client, ensure_schema, insert_rows
from ugc_etl.config import ETLConfig
from ugc_etl.metrics import (
    CLICKHOUSE_ERRORS_TOTAL,
    CONSUMER_GROUP_LAG,
    EVENTS_READ_TOTAL,
    EVENTS_REJECTED_TOTAL,
    EVENTS_SKIPPED_TOTAL,
    EVENTS_WRITTEN_TOTAL,
    INSERT_BATCH_SECONDS,
    INSERT_BATCH_SIZE,
    INSERT_RETRIES_TOTAL,
    KAFKA_ERRORS_TOTAL,
    start_memory_monitoring,
)
from ugc_etl.transform import transform_event


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [ugc-clickhouse-etl] %(message)s",
)
logger = logging.getLogger(__name__)


def _build_consumer(config: ETLConfig) -> KafkaConsumer:
    return KafkaConsumer(
        config.kafka_topic,
        bootstrap_servers=config.kafka_bootstrap_server_list,
        group_id=config.kafka_group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        consumer_timeout_ms=0,
    )


def _insert_with_retries(config: ETLConfig, client, rows: list[tuple]) -> None:
    attempt = 0
    while True:
        try:
            insert_rows(client, config, rows)
            return
        except Exception as exc:
            attempt += 1
            INSERT_RETRIES_TOTAL.inc()
            CLICKHOUSE_ERRORS_TOTAL.inc()
            if attempt > config.max_insert_retries:
                raise RuntimeError("ClickHouse insert retries exhausted.") from exc
            sleep_for = config.retry_backoff_sec * attempt
            logger.warning(
                "ClickHouse insert failed (attempt %s/%s): %s. Retry in %.1fs",
                attempt,
                config.max_insert_retries,
                exc,
                sleep_for,
            )
            time.sleep(sleep_for)


def _commit_offsets(
    consumer: KafkaConsumer, offsets_by_partition: dict[TopicPartition, int]
) -> None:
    if not offsets_by_partition:
        return
    commit_payload = {
        partition: OffsetAndMetadata(offset + 1, None)
        for partition, offset in offsets_by_partition.items()
    }
    consumer.commit(offsets=commit_payload)


def _estimate_consumer_lag(consumer: KafkaConsumer, batch: dict) -> int:
    partitions = list(batch.keys())
    if not partitions:
        return 0
    high_watermarks = consumer.end_offsets(partitions)
    lag_total = 0
    for partition, messages in batch.items():
        if not messages:
            continue
        next_offset = messages[-1].offset + 1
        high = high_watermarks.get(partition, next_offset)
        lag_total += max(high - next_offset, 0)
    return lag_total


def run_forever() -> None:
    config = ETLConfig()
    start_memory_monitoring(config)
    logger.info("Memory metrics available on :%s/metrics", config.memory_metrics_port)

    while True:
        consumer = None
        client = None
        try:
            consumer = _build_consumer(config)
            client = create_client(config)
            ensure_schema(client, config)
            logger.info("Connected to Kafka and ClickHouse.")

            while True:
                batch = consumer.poll(
                    timeout_ms=config.kafka_poll_timeout_ms,
                    max_records=config.kafka_batch_size,
                )
                if not batch:
                    continue

                CONSUMER_GROUP_LAG.set(_estimate_consumer_lag(consumer, batch))
                rows: list[tuple] = []
                offsets_by_partition: dict[TopicPartition, int] = {}

                for partition, messages in batch.items():
                    for message in messages:
                        EVENTS_READ_TOTAL.inc()
                        payload = message.value
                        row, reject_reason = transform_event(payload)
                        if row is None:
                            EVENTS_SKIPPED_TOTAL.inc()
                            if reject_reason:
                                EVENTS_REJECTED_TOTAL.labels(reason=reject_reason).inc()
                        else:
                            rows.append(row)
                        offsets_by_partition[partition] = message.offset

                if rows:
                    INSERT_BATCH_SIZE.observe(len(rows))
                    started_at = time.perf_counter()
                    _insert_with_retries(config, client, rows)
                    INSERT_BATCH_SECONDS.observe(time.perf_counter() - started_at)
                    EVENTS_WRITTEN_TOTAL.inc(len(rows))
                    logger.info("Inserted %s rows into ClickHouse.", len(rows))

                _commit_offsets(consumer, offsets_by_partition)

        except Exception as exc:
            KAFKA_ERRORS_TOTAL.inc()
            logger.exception(
                "ETL loop failed due to source/storage issue: %s. Reconnect in %.1fs",
                exc,
                config.reconnect_backoff_sec,
            )
            time.sleep(config.reconnect_backoff_sec)
        finally:
            if consumer is not None:
                consumer.close()
            if client is not None:
                client.disconnect()


if __name__ == "__main__":
    run_forever()
