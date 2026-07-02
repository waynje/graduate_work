from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from notification_service.config import NotificationSettings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailDeliveryResult:
    provider_message_id: str


class EmailSender:
    def send_email(self, *, user_id: str, subject: str, body: str) -> EmailDeliveryResult:
        raise NotImplementedError


class LogEmailSender(EmailSender):
    def __init__(self, settings: "NotificationSettings"):
        self._settings = settings

    def send_email(self, *, user_id: str, subject: str, body: str) -> EmailDeliveryResult:
        logger.info(
            "EMAIL from=%s to=%s subject=%s body=%s",
            self._settings.notify_default_sender_email,
            user_id,
            subject,
            body[:400],
        )
        return EmailDeliveryResult(provider_message_id=f"log-{uuid.uuid4()}")


def build_email_sender(settings: Any) -> EmailSender:
    if settings.notify_sender_mode == "log":
        return LogEmailSender(settings)
    raise RuntimeError(f"Unsupported sender mode: {settings.notify_sender_mode}")
