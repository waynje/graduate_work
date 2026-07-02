from http import HTTPStatus

import pytest

from tests.functional.settings import test_settings


@pytest.mark.asyncio
async def test_google_login_url_returns_state(make_get_api_request, redis_client):
    status, body = await make_get_api_request("/api/v1/auth/social/google/login-url")
    assert status == HTTPStatus.OK
    assert body["provider"] == "google"
    assert "authorization_url" in body
    assert "state=" in body["authorization_url"]
    assert body["state"]

    state_key = f"auth:oauth:google:state:{body['state']}"
    assert await redis_client.exists(state_key) == 1


@pytest.mark.asyncio
async def test_google_callback_invalid_state(make_post_api_request):
    status, body = await make_post_api_request(
        "/api/v1/auth/social/google/callback",
        payload={"code": "any-code", "state": "invalid-state"},
    )
    assert status == HTTPStatus.BAD_REQUEST
    assert body["detail"] == "invalid oauth state"


@pytest.mark.asyncio
async def test_google_callback_get_missing_code_or_state_redirects(http_client_session):
    base_url = test_settings.service_url.rstrip("/")
    url = f"{base_url}/api/v1/auth/social/google/callback"
    async with http_client_session.get(url, allow_redirects=False) as resp:
        assert resp.status == HTTPStatus.TEMPORARY_REDIRECT
        location = resp.headers.get("Location", "")
        assert "oauth_error=missing_code_or_state" in location
