from types import SimpleNamespace

import pytest

from notification_service.auth_client import fetch_user_profile
from notification_service.shortlink_client import shorten_payload_links


def test_fetch_user_profile_raises_on_error(monkeypatch):
    def _raise(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr("notification_service.auth_client.httpx.get", _raise)
    settings = SimpleNamespace(
        notify_auth_userinfo_url_template="http://auth/api/v1/users/{user_id}",
        notify_auth_request_timeout_sec=1.0,
    )
    with pytest.raises(RuntimeError, match="network down"):
        fetch_user_profile("user-77", settings)


def test_shorten_payload_links_only_for_url_fields(monkeypatch):
    monkeypatch.setattr(
        "notification_service.shortlink_client.shorten_url",
        lambda value, _settings: f"short::{value}",
    )
    payload = {
        "movie_url": "https://movies.local/movie/7",
        "description": "plain text",
    }
    settings = SimpleNamespace(notify_shortlink_base_url="http://short", notify_auth_request_timeout_sec=1.0)
    result = shorten_payload_links(payload, settings)
    assert result["movie_url"].startswith("short::")
    assert result["description"] == "plain text"
