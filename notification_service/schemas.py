from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class TemplateUpsertPayload(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    channel: str = Field(default="email", pattern="^email$")
    subject_template: str = Field(min_length=1, max_length=255)
    body_template: str = Field(min_length=1)
    is_active: bool = True


class InstantNotificationPayload(BaseModel):
    template_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(min_length=1, max_length=64)
    payload: dict = Field(default_factory=dict)
    dedup_key: str | None = Field(default=None, max_length=128)


class BulkNotificationPayload(BaseModel):
    template_id: str = Field(min_length=1, max_length=64)
    user_ids: list[str] = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    dedup_key: str = Field(min_length=1, max_length=128)
    scheduled_for: datetime | None = None

    @field_validator("user_ids")
    @classmethod
    def _validate_user_ids(cls, value: list[str]) -> list[str]:
        filtered = [item.strip() for item in value if item and item.strip()]
        if not filtered:
            raise ValueError("user_ids must contain at least one user.")
        return filtered


class CampaignCreatePayload(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    template_id: str = Field(min_length=1, max_length=64)
    user_ids: list[str] = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    scheduled_for: datetime | None = None
    created_by: str = Field(min_length=1, max_length=64)


class UserPreferencePayload(BaseModel):
    enabled: bool


class RuleCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    template_id: str = Field(min_length=1, max_length=64)
    interval_minutes: int = Field(ge=1, le=10_080)
    user_ids: list[str] = Field(min_length=1)
    payload: dict = Field(default_factory=dict)
    enabled: bool = True


class FixedEventPayload(BaseModel):
    event_type: str = Field(pattern="^(user_registered|new_movie)$")
    user_id: str | None = Field(default=None, max_length=64)
    user_ids: list[str] = Field(default_factory=list)
    payload: dict = Field(default_factory=dict)
    dedup_key: str | None = Field(default=None, max_length=128)


class FreeFormEventPayload(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    template_id: str = Field(min_length=1, max_length=64)
    subject: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)
    type: str = Field(default="email", pattern="^email$")
    dedup_key: str | None = Field(default=None, max_length=128)
