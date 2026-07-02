from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from notification_service.config import NotificationSettings


logger = logging.getLogger(__name__)


def shorten_url(raw_url: str, settings: "NotificationSettings") -> str:
    if not raw_url.startswith(("http://", "https://")):
        return raw_url
    endpoint = f"{settings.notify_shortlink_base_url.rstrip('/')}/api/v1/short-links"
    try:
        response = httpx.post(
            endpoint,
            json={"target_url": raw_url},
            timeout=settings.notify_auth_request_timeout_sec,
        )
        if response.status_code in {200, 201}:
            payload = response.json()
            short_url = payload.get("short_url")
            if isinstance(short_url, str) and short_url:
                return short_url
    except Exception as exc:
        logger.warning("Short link generation failed for url=%s: %s", raw_url, exc)
    return raw_url


def shorten_payload_links(payload: dict, settings: "NotificationSettings") -> dict:
    updated: dict = {}
    for key, value in payload.items():
        if isinstance(value, str) and key.endswith("_url"):
            updated[key] = shorten_url(value, settings)
        else:
            updated[key] = value
    return updated
