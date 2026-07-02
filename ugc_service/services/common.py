from __future__ import annotations

from datetime import datetime


class ServiceValidationError(ValueError):
    """Raised when business input validation fails."""


class NotFoundError(LookupError):
    """Raised when target entity does not exist."""


def serialize_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
