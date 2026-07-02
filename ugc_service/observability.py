from __future__ import annotations

import logging

import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration


logger = logging.getLogger(__name__)
_SENTRY_INITIALIZED = False


def init_sentry(
    *,
    dsn: str | None,
    environment: str,
    traces_sample_rate: float,
    service_name: str,
    with_flask: bool = False,
) -> None:
    global _SENTRY_INITIALIZED
    if _SENTRY_INITIALIZED or not dsn:
        return

    integrations = [FlaskIntegration()] if with_flask else []
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        integrations=integrations,
    )
    sentry_sdk.set_tag("service", service_name)
    _SENTRY_INITIALIZED = True
    logger.info("Sentry initialized for service=%s", service_name)
