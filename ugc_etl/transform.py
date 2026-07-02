from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def transform_event(payload: dict) -> tuple[tuple | None, str | None]:
    if payload.get("event_type") != "page_view":
        return None, "non_page_view"

    event_id = payload.get("event_id") or str(uuid.uuid4())
    session_id = payload.get("session_id")
    page_url = payload.get("page_url")
    duration_ms = payload.get("duration_ms")

    if not session_id or not page_url:
        return None, "missing_required_fields"
    if not isinstance(duration_ms, int) or duration_ms < 0:
        return None, "invalid_duration"

    occurred_at = parse_datetime(payload.get("occurred_at"))
    if occurred_at is None:
        return None, "invalid_occurred_at"
    ingested_at = parse_datetime(payload.get("ingested_at"))
    if ingested_at is None:
        return None, "invalid_ingested_at"

    return (
        event_id,
        str(session_id),
        str(payload["user_id"]) if payload.get("user_id") else None,
        str(page_url),
        duration_ms,
        str(payload["referrer"]) if payload.get("referrer") else None,
        occurred_at,
        ingested_at,
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
    ), None


def to_clickhouse_row(payload: dict) -> tuple | None:
    row, _ = transform_event(payload)
    return row
