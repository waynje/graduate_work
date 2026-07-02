import threading
import time

import psutil
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from ugc_etl.config import ETLConfig


MEMORY_RSS_BYTES = Gauge("ugc_etl_memory_rss_bytes", "Resident memory used by ETL process")
MEMORY_VMS_BYTES = Gauge("ugc_etl_memory_vms_bytes", "Virtual memory used by ETL process")
EVENTS_READ_TOTAL = Counter("ugc_etl_events_read_total", "Total Kafka events read")
EVENTS_WRITTEN_TOTAL = Counter(
    "ugc_etl_events_written_total", "Total page_view events written to ClickHouse"
)
EVENTS_SKIPPED_TOTAL = Counter(
    "ugc_etl_events_skipped_total", "Total events skipped by ETL validation"
)
EVENTS_REJECTED_TOTAL = Counter(
    "ugc_etl_events_rejected_total",
    "Total events rejected by validation grouped by reason",
    labelnames=("reason",),
)
INSERT_RETRIES_TOTAL = Counter(
    "ugc_etl_insert_retries_total", "Total retries for ClickHouse inserts"
)
KAFKA_ERRORS_TOTAL = Counter("ugc_etl_kafka_errors_total", "Total Kafka consumer errors")
CLICKHOUSE_ERRORS_TOTAL = Counter(
    "ugc_etl_clickhouse_errors_total", "Total ClickHouse insert errors"
)
INSERT_BATCH_SECONDS = Histogram(
    "ugc_etl_insert_batch_seconds",
    "Duration of ClickHouse batch insert",
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
INSERT_BATCH_SIZE = Histogram(
    "ugc_etl_insert_batch_size",
    "Rows in a single ClickHouse insert batch",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000),
)
CONSUMER_GROUP_LAG = Gauge("ugc_etl_consumer_group_lag", "Estimated lag for consumed batch")


def start_memory_monitoring(config: ETLConfig) -> None:
    start_http_server(config.memory_metrics_port)
    process = psutil.Process()

    def _poll_memory() -> None:
        while True:
            info = process.memory_info()
            MEMORY_RSS_BYTES.set(info.rss)
            MEMORY_VMS_BYTES.set(info.vms)
            time.sleep(config.memory_metrics_interval_sec)

    thread = threading.Thread(target=_poll_memory, daemon=True)
    thread.start()
