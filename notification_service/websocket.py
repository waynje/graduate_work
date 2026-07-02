from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import WebSocket
from sqlalchemy import select

from notification_service.db import session_scope
from notification_service.models import NotificationDelivery


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def fetch_user_deliveries(user_id: str, *, limit: int = 50) -> list[dict]:
    with session_scope() as session:
        rows = session.scalars(
            select(NotificationDelivery)
            .where(NotificationDelivery.user_id == user_id)
            .order_by(NotificationDelivery.created_at.desc())
            .limit(limit)
        ).all()

    return [
        {
            "delivery_id": row.id,
            "request_id": row.request_id,
            "channel": row.channel,
            "status": row.status,
            "subject": row.subject,
            "provider_message_id": row.provider_message_id,
            "error": row.error,
            "sent_at": _serialize_datetime(row.sent_at),
            "created_at": _serialize_datetime(row.created_at),
        }
        for row in rows
    ]


async def stream_user_deliveries(websocket: WebSocket, user_id: str, poll_interval_sec: float) -> None:
    await websocket.accept()
    last_signature: tuple[str, ...] = tuple()
    try:
        while True:
            deliveries = fetch_user_deliveries(user_id)
            signature = tuple(item["delivery_id"] for item in deliveries)
            if signature != last_signature:
                await websocket.send_json(
                    {
                        "type": "deliveries_snapshot",
                        "user_id": user_id,
                        "count": len(deliveries),
                        "items": deliveries,
                    }
                )
                last_signature = signature
            await asyncio.sleep(poll_interval_sec)
    except Exception:
        await websocket.close()
