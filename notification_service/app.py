from __future__ import annotations

import logging
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import FastAPI, Header, HTTPException, Query, WebSocket, status
from fastapi.responses import HTMLResponse

from notification_service.config import NotificationSettings, get_notification_settings
from notification_service.db import init_engine, run_migrations
from notification_service.producer import NotificationProducer
from notification_service.schemas import (
    BulkNotificationPayload,
    CampaignCreatePayload,
    FixedEventPayload,
    FreeFormEventPayload,
    InstantNotificationPayload,
    RuleCreatePayload,
    TemplateUpsertPayload,
    UserPreferencePayload,
)
from notification_service.service import (
    NotificationError,
    collect_known_user_ids,
    create_automatic_rule,
    create_campaign,
    delete_template,
    enqueue_request,
    list_templates,
    set_user_preference,
    upsert_template,
)
from notification_service.websocket import fetch_user_deliveries, stream_user_deliveries


logger = logging.getLogger(__name__)

FIXED_EVENT_TEMPLATE_MAP = {
    "user_registered": "event_user_registered",
    "new_movie": "event_new_movie",
}


def _check_admin_token(token: str | None, settings: NotificationSettings) -> None:
    if not token or not secrets.compare_digest(token, settings.notify_admin_api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token.")


def _ensure_default_templates() -> None:
    upsert_template(
        template_id="event_user_registered",
        channel="email",
        subject_template="Добро пожаловать, ${first_name}",
        body_template="Рады видеть вас в Movies, ${first_name}. Начните с подборки: ${movie_url}",
        is_active=True,
    )
    upsert_template(
        template_id="event_new_movie",
        channel="email",
        subject_template="Новый фильм уже в каталоге",
        body_template="Привет, ${first_name}! Для вас добавлен новый фильм: ${movie_url}",
        is_active=True,
    )


def create_app(settings: NotificationSettings | None = None) -> FastAPI:
    settings = settings or get_notification_settings()
    app = FastAPI(title="notification-service", version="1.0.0")
    app.state.settings = settings

    @app.on_event("startup")
    def on_startup() -> None:
        init_engine(settings.notify_database_url)
        if settings.notify_run_migrations_on_startup:
            run_migrations(settings.notify_database_url)
        _ensure_default_templates()
        app.state.producer = NotificationProducer(
            bootstrap_servers=settings.notify_kafka_bootstrap_servers,
            topic=settings.notify_kafka_topic,
        )

    @app.on_event("shutdown")
    def on_shutdown() -> None:
        producer = getattr(app.state, "producer", None)
        if producer is not None:
            producer.close()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/admin/notifications", response_class=HTMLResponse)
    def admin_panel(token: str = Query(default="")) -> str:
        _check_admin_token(token, settings)
        return """
<html>
  <body>
    <h2>Notification Admin Panel</h2>
    <p>Use manager token via <code>X-Admin-Token</code> for API calls.</p>
    <ul>
      <li>Create/update templates: <code>POST /api/v1/admin/templates</code></li>
      <li>Create campaign now or delayed: <code>POST /api/v1/admin/campaigns</code></li>
      <li>Create recurring rules: <code>POST /api/v1/admin/auto-rules</code></li>
      <li>Broadcast all known users: <code>POST /api/v1/notifications/broadcast</code></li>
    </ul>
  </body>
</html>
"""

    @app.post("/api/v1/admin/templates")
    def admin_upsert_template(
        payload: TemplateUpsertPayload,
        x_admin_token: str | None = Header(default=None),
    ) -> dict:
        _check_admin_token(x_admin_token, settings)
        row = upsert_template(
            template_id=payload.id,
            channel=payload.channel,
            subject_template=payload.subject_template,
            body_template=payload.body_template,
            is_active=payload.is_active,
        )
        return {"status": "ok", "template_id": row.id}

    @app.get("/api/v1/admin/templates")
    def admin_list_templates(x_admin_token: str | None = Header(default=None)) -> dict:
        _check_admin_token(x_admin_token, settings)
        rows = list_templates()
        return {
            "status": "ok",
            "items": [
                {"id": row.id, "channel": row.channel, "is_active": row.is_active}
                for row in rows
            ],
        }

    @app.delete("/api/v1/admin/templates/{template_id}")
    def admin_delete_template(template_id: str, x_admin_token: str | None = Header(default=None)) -> dict:
        _check_admin_token(x_admin_token, settings)
        if not delete_template(template_id):
            raise HTTPException(status_code=404, detail="Template not found.")
        return {"status": "ok", "deleted": True}

    @app.post("/api/v1/users/{user_id}/preferences/email")
    def set_email_preference(user_id: str, payload: UserPreferencePayload) -> dict:
        row = set_user_preference(user_id=user_id, channel="email", enabled=payload.enabled)
        return {"status": "ok", "user_id": row.user_id, "channel": row.channel, "enabled": row.enabled}

    @app.get("/api/v1/users/{user_id}/notifications")
    def list_user_notifications(user_id: str) -> dict:
        return {"status": "ok", "user_id": user_id, "items": fetch_user_deliveries(user_id)}

    @app.post("/api/v1/notifications/instant")
    def create_instant_notification(
        payload: InstantNotificationPayload,
        x_admin_token: str | None = Header(default=None),
    ) -> dict:
        _check_admin_token(x_admin_token, settings)
        dedup_key = payload.dedup_key or f"instant:{payload.template_id}:{payload.user_id}:{datetime.now(UTC).isoformat()}"
        try:
            request_row, created = enqueue_request(
                source_type="instant",
                template_id=payload.template_id,
                user_ids=[payload.user_id],
                payload=payload.payload,
                dedup_key=dedup_key,
            )
        except NotificationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if created:
            try:
                app.state.producer.publish_request(request_row.id)
            except Exception as exc:
                logger.warning("Failed to enqueue instant notification=%s to Kafka: %s", request_row.id, exc)
        return {"status": "accepted", "request_id": request_row.id, "created": created}

    @app.post("/api/v1/notifications/broadcast")
    def create_broadcast_notification(
        payload: BulkNotificationPayload,
        x_admin_token: str | None = Header(default=None),
    ) -> dict:
        _check_admin_token(x_admin_token, settings)
        user_ids = collect_known_user_ids()
        if not user_ids:
            raise HTTPException(status_code=422, detail="No known users to broadcast.")
        try:
            request_row, created = enqueue_request(
                source_type="broadcast",
                template_id=payload.template_id,
                user_ids=user_ids,
                payload=payload.payload,
                dedup_key=payload.dedup_key,
                scheduled_for=payload.scheduled_for,
            )
        except NotificationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if created:
            try:
                app.state.producer.publish_request(request_row.id)
            except Exception as exc:
                logger.warning("Failed to enqueue broadcast notification=%s to Kafka: %s", request_row.id, exc)
        return {
            "status": "accepted",
            "request_id": request_row.id,
            "created": created,
            "users_count": len(user_ids),
        }

    @app.post("/api/v1/notifications/bulk")
    def create_bulk_notification(
        payload: BulkNotificationPayload,
        x_admin_token: str | None = Header(default=None),
    ) -> dict:
        _check_admin_token(x_admin_token, settings)
        try:
            request_row, created = enqueue_request(
                source_type="bulk",
                template_id=payload.template_id,
                user_ids=payload.user_ids,
                payload=payload.payload,
                dedup_key=payload.dedup_key,
                scheduled_for=payload.scheduled_for,
            )
        except NotificationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if created:
            try:
                app.state.producer.publish_request(request_row.id)
            except Exception as exc:
                logger.warning("Failed to enqueue bulk notification=%s to Kafka: %s", request_row.id, exc)
        return {"status": "accepted", "request_id": request_row.id, "created": created}

    @app.post("/api/v1/admin/campaigns")
    def create_admin_campaign(
        payload: CampaignCreatePayload,
        x_admin_token: str | None = Header(default=None),
    ) -> dict:
        _check_admin_token(x_admin_token, settings)
        try:
            campaign, request_row, created = create_campaign(
                title=payload.title,
                template_id=payload.template_id,
                user_ids=payload.user_ids,
                payload=payload.payload,
                scheduled_for=payload.scheduled_for,
                created_by=payload.created_by,
            )
        except NotificationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if created:
            try:
                app.state.producer.publish_request(request_row.id)
            except Exception as exc:
                logger.warning("Failed to enqueue campaign notification=%s to Kafka: %s", request_row.id, exc)
        return {"status": "accepted", "campaign_id": campaign.id, "request_id": request_row.id}

    @app.post("/api/v1/admin/auto-rules")
    def create_auto_rule(payload: RuleCreatePayload, x_admin_token: str | None = Header(default=None)) -> dict:
        _check_admin_token(x_admin_token, settings)
        try:
            rule = create_automatic_rule(
                name=payload.name,
                template_id=payload.template_id,
                interval_minutes=payload.interval_minutes,
                user_ids=payload.user_ids,
                payload=payload.payload,
                enabled=payload.enabled,
            )
        except NotificationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"status": "ok", "rule_id": rule.id, "next_run_at": rule.next_run_at}

    @app.post("/api/v1/events/fixed")
    def process_fixed_event(payload: FixedEventPayload) -> dict:
        template_id = FIXED_EVENT_TEMPLATE_MAP[payload.event_type]
        user_ids = payload.user_ids or ([payload.user_id] if payload.user_id else [])
        if not user_ids:
            raise HTTPException(status_code=422, detail="fixed event requires user_id or user_ids.")
        dedup_key = payload.dedup_key or (
            f"fixed:{payload.event_type}:{','.join(sorted(user_ids))}:{datetime.now(UTC).replace(second=0, microsecond=0).isoformat()}"
        )
        try:
            request_row, created = enqueue_request(
                source_type=f"fixed_{payload.event_type}",
                template_id=template_id,
                user_ids=user_ids,
                payload=payload.payload,
                dedup_key=dedup_key,
            )
        except NotificationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if created:
            try:
                app.state.producer.publish_request(request_row.id)
            except Exception as exc:
                logger.warning("Failed to enqueue fixed event=%s: %s", request_row.id, exc)
        return {"status": "accepted", "request_id": request_row.id, "created": created}

    @app.post("/api/v1/events/free-form")
    def process_free_form_event(
        payload: FreeFormEventPayload,
        x_admin_token: str | None = Header(default=None),
    ) -> dict:
        _check_admin_token(x_admin_token, settings)
        template_id = f"dynamic_{payload.template_id}"
        upsert_template(
            template_id=template_id,
            channel=payload.type,
            subject_template=payload.subject,
            body_template=payload.text,
            is_active=True,
        )
        dedup_key = payload.dedup_key or f"free-form:{payload.user_id}:{payload.template_id}:{uuid.uuid4()}"
        request_row, created = enqueue_request(
            source_type="free_form",
            template_id=template_id,
            user_ids=[payload.user_id],
            payload={},
            dedup_key=dedup_key,
        )
        if created:
            try:
                app.state.producer.publish_request(request_row.id)
            except Exception as exc:
                logger.warning("Failed to enqueue free-form event=%s: %s", request_row.id, exc)
        return {"status": "accepted", "request_id": request_row.id, "created": created}

    @app.websocket("/ws/v1/users/{user_id}/notifications")
    async def ws_user_notifications(websocket: WebSocket, user_id: str) -> None:
        token = websocket.query_params.get("token")
        if not token or not secrets.compare_digest(token, settings.notify_websocket_api_token):
            await websocket.close(code=4401, reason="Unauthorized websocket token.")
            return
        await stream_user_deliveries(
            websocket=websocket,
            user_id=user_id,
            poll_interval_sec=settings.notify_websocket_poll_interval_sec,
        )

    return app


app = create_app()
