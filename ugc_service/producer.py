import json
import logging
import time
import uuid
from datetime import datetime, timezone

from kafka import KafkaProducer

logger = logging.getLogger(__name__)


class EventProducer:
    def __init__(
        self,
        bootstrap_servers: list[str],
        topic: str,
        max_retries: int = 2,
        retry_backoff_sec: float = 0.2,
        send_timeout_sec: float = 2.0,
        acks: str = "all",
        producer_retries: int = 2,
        linger_ms: int = 5,
        request_timeout_ms: int = 5000,
        max_in_flight_requests_per_connection: int = 1,
    ):
        self.topic = topic
        self.max_retries = max_retries
        self.retry_backoff_sec = retry_backoff_sec
        self.send_timeout_sec = send_timeout_sec
        self._bootstrap_servers = bootstrap_servers
        self._acks = acks
        self._producer_retries = producer_retries
        self._linger_ms = linger_ms
        self._request_timeout_ms = request_timeout_ms
        self._max_in_flight_requests_per_connection = max_in_flight_requests_per_connection
        self._producer = None

    def _create_producer(self) -> KafkaProducer:
        return KafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            key_serializer=lambda key: key.encode("utf-8") if key else None,
            acks=self._acks,
            retries=self._producer_retries,
            linger_ms=self._linger_ms,
            request_timeout_ms=self._request_timeout_ms,
            max_in_flight_requests_per_connection=self._max_in_flight_requests_per_connection,
        )

    def _get_producer(self) -> KafkaProducer:
        if self._producer is None:
            self._producer = self._create_producer()
        return self._producer

    def send(self, payload: dict) -> None:
        # Kafka key by session allows ordering for one user journey.
        value = {
            **payload,
            "event_id": str(uuid.uuid4()),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }
        attempt = 0
        deadline = time.monotonic() + self.send_timeout_sec
        while True:
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Kafka publish total timeout exceeded.")
                producer = self._get_producer()
                future = producer.send(
                    topic=self.topic,
                    key=payload.get("session_id"),
                    value=value,
                )
                future.get(timeout=max(0.1, remaining))
                return
            except Exception as exc:
                attempt += 1
                self.close()
                remaining = deadline - time.monotonic()
                if attempt > self.max_retries or remaining <= 0:
                    raise RuntimeError("Kafka producer retries exhausted.") from exc
                sleep_for = min(self.retry_backoff_sec * attempt, max(0.0, remaining))
                logger.warning(
                    "Kafka publish failed (attempt %s/%s): %s. Retry in %.2fs",
                    attempt,
                    self.max_retries,
                    exc,
                    sleep_for,
                )
                if sleep_for > 0:
                    time.sleep(sleep_for)

    def close(self) -> None:
        if self._producer is None:
            return
        self._producer.close()
        self._producer = None
