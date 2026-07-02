from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

ALLOWED_CUSTOM_EVENT_NAMES = (
    "video_quality_change",
    "video_completed",
    "search_filter_used",
)


def _serialize_dt(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class EventBaseSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=64)
    page_url: Optional[str] = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("occurred_at")
    @classmethod
    def normalize_occurred_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def base_payload(self, user_id: Optional[str]) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": user_id,
            "page_url": self.page_url,
            "occurred_at": _serialize_dt(self.occurred_at),
        }


class ClickEventSchema(EventBaseSchema):
    element: str = Field(min_length=1, max_length=128)
    metadata: dict = Field(default_factory=dict)


class PageViewEventSchema(EventBaseSchema):
    page_url: str = Field(min_length=1)
    duration_ms: int = Field(ge=0)
    referrer: Optional[str] = None


class CustomEventSchema(EventBaseSchema):
    event_name: Literal[*ALLOWED_CUSTOM_EVENT_NAMES]
    attributes: dict = Field(default_factory=dict)


def validate_click_event(payload: dict, user_id: Optional[str]) -> dict:
    event = ClickEventSchema.model_validate(payload)
    data = event.base_payload(user_id=user_id)
    data.update(
        {
            "event_type": "click",
            "event_name": "ui_click",
            "element": event.element,
            "metadata": event.metadata,
        }
    )
    return data


def validate_page_view_event(payload: dict, user_id: Optional[str]) -> dict:
    event = PageViewEventSchema.model_validate(payload)
    data = event.base_payload(user_id=user_id)
    data.update(
        {
            "event_type": "page_view",
            "event_name": "page_view",
            "duration_ms": event.duration_ms,
            "referrer": event.referrer,
        }
    )
    return data


def validate_custom_event(payload: dict, user_id: Optional[str]) -> dict:
    event = CustomEventSchema.model_validate(payload)
    data = event.base_payload(user_id=user_id)
    data.update(
        {
            "event_type": "custom",
            "event_name": event.event_name,
            "attributes": event.attributes,
        }
    )
    return data


__all__ = [
    "ALLOWED_CUSTOM_EVENT_NAMES",
    "ValidationError",
    "validate_click_event",
    "validate_custom_event",
    "validate_page_view_event",
]
