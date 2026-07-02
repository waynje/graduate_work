from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta

from kafka import KafkaConsumer, TopicPartition
from kafka.structs import OffsetAndMetadata
from sqlalchemy import select

from notification_service.auth_client import fetch_user_profile
from notification_service.config import NotificationSettings, get_notification_settings
from notification_service.db import init_engine, run_migrations, session_scope
from notification_service.email_sender import build_email_sender
from notification_service.models import (
    NotificationDelivery,
    NotificationRequest,
    NotificationTemplate,
    UserNotificationPreference,
)
from notification_service.personalized_email import render_personalized_email
from notification_service.shortlink_client import shorten_payload_links


logger = logging.getLogger(__name__)


def _is_enabled_for_user(user_id: str, channel: str) -> bool:
    with session_scope() as session:
        pref = session.scalar(
            select(UserNotificationPreference).where(
                UserNotificationPreference.user_id == user_id,
                UserNotificationPreference.channel == channel,
            )
        )
    return True if pref is None else pref.enabled


def _fetch_pending_request(request_id: str | None = None) -> NotificationRequest | None:
    with session_scope() as session:
        if request_id:
            row = session.get(NotificationRequest, request_id)
            if row is None:
                return None
            if row.status not in {"pending", "processing"}:
                return None
            if row.next_attempt_at > datetime.now(UTC):
                return None
            row.status = "processing"
            return row

        row = session.scalar(
            select(NotificationRequest)
            .where(
                NotificationRequest.status.in_(["pending", "processing"]),
                NotificationRequest.next_attempt_at <= datetime.now(UTC),
            )
            .order_by(NotificationRequest.created_at.asc())
            .limit(1)
        )
        if row is None:
            return None
        row.status = "processing"
        return row


def _record_delivery(
    *,
    request_id: str,
    user_id: str,
    channel: str,
    subject: str,
    body: str,
    status: str,
    provider_message_id: str | None,
    error: str | None = None,
) -> None:
    with session_scope() as session:
        existing = session.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.request_id == request_id,
                NotificationDelivery.user_id == user_id,
                NotificationDelivery.channel == channel,
            )
        )
        if existing is not None:
            return
        session.add(
            NotificationDelivery(
                id=str(uuid.uuid4()),
                request_id=request_id,
                user_id=user_id,
                channel=channel,
                status=status,
                subject=subject,
                body=body,
                provider_message_id=provider_message_id,
                error=error,
                sent_at=datetime.now(UTC) if status == "sent" else None,
            )
        )


def _mark_request_result(request_id: str, *, success: bool, error: str | None, settings: NotificationSettings) -> None:
    with session_scope() as session:
        row = session.get(NotificationRequest, request_id)
        if row is None:
            return
        if success:
            row.status = "done"
            row.last_error = None
            return
        row.attempt_count += 1
        row.last_error = error
        if row.attempt_count >= settings.notify_worker_max_attempts:
            row.status = "failed"
        else:
            row.status = "pending"
            row.next_attempt_at = datetime.now(UTC) + timedelta(seconds=30 * row.attempt_count)


def process_request(request_id: str, settings: NotificationSettings) -> bool:
    row = _fetch_pending_request(request_id)
    if row is None:
        return False

    with session_scope() as session:
        template = session.get(NotificationTemplate, row.template_id)
    if template is None or not template.is_active:
        _mark_request_result(
            row.id, success=False, error=f"template '{row.template_id}' unavailable", settings=settings
        )
        return False

    try:
        email_sender = build_email_sender(settings)
        for user_id in row.recipient_user_ids:
            if not _is_enabled_for_user(user_id, template.channel):
                _record_delivery(
                    request_id=row.id,
                    user_id=user_id,
                    channel=template.channel,
                    subject="skipped by preference",
                    body="",
                    status="skipped",
                    provider_message_id=None,
                )
                continue
            profile = fetch_user_profile(user_id=user_id, settings=settings)
            payload = {**shorten_payload_links(row.payload, settings), **profile}
            personalized_email = render_personalized_email(
                user_id=user_id,
                payload=payload,
                subject_template=template.subject_template,
                body_template=template.body_template,
            )
            send_result = email_sender.send_email(
                user_id=user_id,
                subject=personalized_email.subject,
                body=personalized_email.body,
            )
            _record_delivery(
                request_id=row.id,
                user_id=user_id,
                channel=template.channel,
                subject=personalized_email.subject,
                body=personalized_email.body,
                status="sent",
                provider_message_id=send_result.provider_message_id,
            )
        _mark_request_result(row.id, success=True, error=None, settings=settings)
        return True
    except Exception as exc:
        logger.exception("Failed to process notification request=%s: %s", row.id, exc)
        _mark_request_result(row.id, success=False, error=str(exc), settings=settings)
        return False


def _create_consumer(settings: NotificationSettings) -> KafkaConsumer | None:
    try:
        return KafkaConsumer(
            settings.notify_kafka_topic,
            bootstrap_servers=settings.notify_kafka_bootstrap_servers,
            group_id=settings.notify_kafka_group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        )
    except Exception:
        logger.warning("Kafka unavailable for notification-worker. Falling back to DB polling only.")
        return None


def _consume_request_ids(
    consumer: KafkaConsumer, settings: NotificationSettings
) -> list[tuple[str, TopicPartition, int]]:
    records = consumer.poll(timeout_ms=1000, max_records=settings.notify_worker_batch_size)
    request_messages: list[tuple[str, TopicPartition, int]] = []
    for topic_partition, messages in records.items():
        for message in messages:
            payload = message.value if isinstance(message.value, dict) else {}
            request_id = payload.get("request_id")
            if isinstance(request_id, str):
                request_messages.append((request_id, topic_partition, message.offset))
    return request_messages


def run_worker(settings: NotificationSettings | None = None) -> None:
    settings = settings or get_notification_settings()
    init_engine(settings.notify_database_url)
    if settings.notify_run_migrations_on_startup:
        run_migrations(settings.notify_database_url)

    logger.info("notification-worker started")
    consumer = _create_consumer(settings)
    try:
        while True:
            processed = False
            if consumer is not None:
                try:
                    consumed_messages = _consume_request_ids(consumer, settings)
                    for request_id, topic_partition, offset in consumed_messages:
                        success = process_request(request_id, settings)
                        processed = success or processed
                        if success:
                            consumer.commit(
                                {topic_partition: OffsetAndMetadata(offset + 1, None)}
                            )
                except Exception as exc:
                    logger.warning("Kafka consume loop failed, recreating consumer: %s", exc)
                    try:
                        consumer.close()
                    except Exception:
                        logger.debug("Kafka consumer close failed during recreate.", exc_info=True)
                    consumer = _create_consumer(settings)

            while True:
                row = _fetch_pending_request()
                if row is None:
                    break
                processed = process_request(row.id, settings) or processed

            if not processed:
                if consumer is None:
                    consumer = _create_consumer(settings)
                time.sleep(settings.notify_worker_poll_interval_sec)
    finally:
        if consumer is not None:
            consumer.close()


if __name__ == "__main__":
    run_worker()
