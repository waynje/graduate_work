from __future__ import annotations

import logging
import time

from notification_service.config import NotificationSettings, get_notification_settings
from notification_service.db import init_engine, run_migrations
from notification_service.producer import NotificationProducer
from notification_service.service import schedule_due_rules


logger = logging.getLogger(__name__)


def run_scheduler(settings: NotificationSettings | None = None) -> None:
    settings = settings or get_notification_settings()
    init_engine(settings.notify_database_url)
    if settings.notify_run_migrations_on_startup:
        run_migrations(settings.notify_database_url)
    producer = NotificationProducer(
        bootstrap_servers=settings.notify_kafka_bootstrap_servers,
        topic=settings.notify_kafka_topic,
    )
    try:
        logger.info("notification-scheduler started")
        while True:
            request_ids = schedule_due_rules()
            for request_id in request_ids:
                try:
                    producer.publish_request(request_id)
                except Exception as exc:
                    logger.warning("Failed to publish auto notification request=%s: %s", request_id, exc)
            time.sleep(settings.notify_scheduler_poll_interval_sec)
    finally:
        producer.close()


if __name__ == "__main__":
    run_scheduler()
