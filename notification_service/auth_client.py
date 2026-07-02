from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from notification_service.config import NotificationSettings


logger = logging.getLogger(__name__)


def fetch_user_profile(user_id: str, settings: "NotificationSettings") -> dict:
    url = settings.notify_auth_userinfo_url_template.format(user_id=user_id)
    try:
        response = httpx.get(url, timeout=settings.notify_auth_request_timeout_sec)
        response.raise_for_status()
        payload = response.json()
        first_name = payload.get("first_name") or payload.get("login") or user_id
        last_name = payload.get("last_name") or ""
        email = payload.get("email")
        if not email:
            raise ValueError(f"Auth profile for user={user_id} has no email")
        return {
            "first_name": str(first_name),
            "last_name": str(last_name),
            "full_name": f"{first_name} {last_name}".strip(),
            "email": str(email),
        }
    except Exception as exc:
        logger.warning("Auth profile lookup failed for user=%s: %s", user_id, exc)
        raise
