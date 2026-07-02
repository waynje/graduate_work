from __future__ import annotations

import json
import logging

from kafka import KafkaProducer


logger = logging.getLogger(__name__)


class NotificationProducer:
    def __init__(self, bootstrap_servers: list[str], topic: str):
        self.topic = topic
        self._producer = KafkaProducer(
            bootstrap_servers=bootstrap_servers,
            value_serializer=lambda value: json.dumps(value).encode("utf-8"),
            acks="all",
            retries=3,
            linger_ms=5,
            request_timeout_ms=5000,
        )

    def publish_request(self, request_id: str) -> None:
        future = self._producer.send(self.topic, value={"request_id": request_id})
        future.get(timeout=2)

    def close(self) -> None:
        self._producer.close()
