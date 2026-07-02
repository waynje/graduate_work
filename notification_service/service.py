from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from notification_service.db import session_scope
from notification_service.models import (
    AutomaticNotificationRule,
    NotificationCampaign,
    NotificationRequest,
    NotificationTemplate,
    UserNotificationPreference,
)


logger = logging.getLogger(__name__)


class NotificationError(RuntimeError):
    pass


def upsert_template(
    template_id: str,
    channel: str,
    subject_template: str,
    body_template: str,
    is_active: bool,
) -> NotificationTemplate:
    with session_scope() as session:
        row = session.get(NotificationTemplate, template_id)
        if row is None:
            row = NotificationTemplate(
                id=template_id,
                channel=channel,
                subject_template=subject_template,
                body_template=body_template,
                is_active=is_active,
            )
            session.add(row)
        else:
            row.channel = channel
            row.subject_template = subject_template
            row.body_template = body_template
            row.is_active = is_active
    return row


def list_templates() -> list[NotificationTemplate]:
    with session_scope() as session:
        return session.scalars(select(NotificationTemplate).order_by(NotificationTemplate.id.asc())).all()


def delete_template(template_id: str) -> bool:
    with session_scope() as session:
        row = session.get(NotificationTemplate, template_id)
        if row is None:
            return False
        session.delete(row)
        return True


def _ensure_template_exists(template_id: str) -> None:
    with session_scope() as session:
        template = session.get(NotificationTemplate, template_id)
    if template is None or not template.is_active:
        raise NotificationError(f"Template '{template_id}' does not exist or is inactive.")


def enqueue_request(
    source_type: str,
    template_id: str,
    user_ids: list[str],
    payload: dict,
    dedup_key: str,
    scheduled_for: datetime | None = None,
    campaign_id: str | None = None,
) -> tuple[NotificationRequest, bool]:
    _ensure_template_exists(template_id)
    next_attempt_at = scheduled_for.astimezone(UTC) if scheduled_for else datetime.now(UTC)
    with session_scope() as session:
        existing = session.scalar(
            select(NotificationRequest).where(NotificationRequest.dedup_key == dedup_key)
        )
        if existing is not None:
            return existing, False

        request_row = NotificationRequest(
            id=str(uuid.uuid4()),
            source_type=source_type,
            template_id=template_id,
            recipient_user_ids=user_ids,
            payload=payload,
            dedup_key=dedup_key,
            status="pending",
            next_attempt_at=next_attempt_at,
            campaign_id=campaign_id,
        )
        session.add(request_row)
    return request_row, True


def create_campaign(
    *,
    title: str,
    template_id: str,
    user_ids: list[str],
    payload: dict,
    scheduled_for: datetime | None,
    created_by: str,
) -> tuple[NotificationCampaign, NotificationRequest, bool]:
    _ensure_template_exists(template_id)
    campaign_id = str(uuid.uuid4())
    with session_scope() as session:
        campaign = NotificationCampaign(
            id=campaign_id,
            title=title,
            created_by=created_by,
            template_id=template_id,
            recipient_user_ids=user_ids,
            payload=payload,
            scheduled_for=scheduled_for,
        )
        session.add(campaign)
    request, created = enqueue_request(
        source_type="campaign",
        template_id=template_id,
        user_ids=user_ids,
        payload=payload,
        dedup_key=f"campaign:{campaign_id}",
        scheduled_for=scheduled_for,
        campaign_id=campaign_id,
    )
    return campaign, request, created


def set_user_preference(user_id: str, channel: str, enabled: bool) -> UserNotificationPreference:
    with session_scope() as session:
        row = session.scalar(
            select(UserNotificationPreference).where(
                UserNotificationPreference.user_id == user_id,
                UserNotificationPreference.channel == channel,
            )
        )
        if row is None:
            row = UserNotificationPreference(user_id=user_id, channel=channel, enabled=enabled)
            session.add(row)
        else:
            row.enabled = enabled
    return row


def collect_known_user_ids(limit: int = 5000) -> list[str]:
    with session_scope() as session:
        prefs = session.scalars(select(UserNotificationPreference.user_id).limit(limit)).all()
        reqs = session.scalars(select(NotificationRequest.recipient_user_ids).limit(limit)).all()
    collected = {user_id for user_id in prefs}
    for group in reqs:
        for user_id in group:
            collected.add(user_id)
    return sorted(collected)


def create_automatic_rule(
    *,
    name: str,
    template_id: str,
    interval_minutes: int,
    user_ids: list[str],
    payload: dict,
    enabled: bool,
) -> AutomaticNotificationRule:
    _ensure_template_exists(template_id)
    with session_scope() as session:
        rule = AutomaticNotificationRule(
            id=str(uuid.uuid4()),
            name=name,
            template_id=template_id,
            interval_minutes=interval_minutes,
            recipient_user_ids=user_ids,
            payload=payload,
            enabled=enabled,
            next_run_at=datetime.now(UTC),
        )
        session.add(rule)
    return rule


def schedule_due_rules(limit: int = 100) -> list[str]:
    created_request_ids: list[str] = []
    now = datetime.now(UTC)
    with session_scope() as session:
        rules = session.scalars(
            select(AutomaticNotificationRule)
            .where(
                AutomaticNotificationRule.enabled.is_(True),
                AutomaticNotificationRule.next_run_at <= now,
            )
            .order_by(AutomaticNotificationRule.next_run_at.asc())
            .limit(limit)
        ).all()
        for rule in rules:
            run_slot = rule.next_run_at.astimezone(UTC).replace(second=0, microsecond=0).isoformat()
            dedup_key = f"rule:{rule.id}:{run_slot}"
            existing = session.scalar(
                select(NotificationRequest).where(NotificationRequest.dedup_key == dedup_key)
            )
            if existing is None:
                request_row = NotificationRequest(
                    id=str(uuid.uuid4()),
                    source_type="auto_rule",
                    template_id=rule.template_id,
                    recipient_user_ids=rule.recipient_user_ids,
                    payload=rule.payload,
                    dedup_key=dedup_key,
                    status="pending",
                    next_attempt_at=now,
                )
                session.add(request_row)
                created_request_ids.append(request_row.id)
            rule.last_run_at = now
            rule.next_run_at = now + timedelta(minutes=rule.interval_minutes)
    return created_request_ids
