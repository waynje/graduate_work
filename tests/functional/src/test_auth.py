from http import HTTPStatus

import pytest


@pytest.mark.asyncio
async def test_auth_register_login_me_logout_flow(make_post_api_request, make_get_api_request):
    register_payload = {"login": "alice", "password": "StrongPass123"}
    status, body = await make_post_api_request("/api/v1/auth/register", payload=register_payload)
    assert status == HTTPStatus.CREATED
    assert body["login"] == "alice"
    assert "user" in body["roles"]

    status, body = await make_post_api_request("/api/v1/auth/login", payload=register_payload)
    assert status == HTTPStatus.OK
    assert "access_token" in body and "refresh_token" in body

    headers = {"Authorization": f"Bearer {body['access_token']}"}
    status_me, me_body = await make_get_api_request("/api/v1/auth/me", headers=headers)
    assert status_me == HTTPStatus.OK
    assert me_body["login"] == "alice"

    status_logout, _ = await make_post_api_request(
        "/api/v1/auth/logout",
        payload={"refresh_token": body["refresh_token"]},
        headers=headers,
    )
    assert status_logout == HTTPStatus.NO_CONTENT

    status_me_after, _ = await make_get_api_request("/api/v1/auth/me", headers=headers)
    assert status_me_after == HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_auth_refresh_rotation(make_post_api_request):
    creds = {"login": "bob", "password": "StrongPass123"}
    await make_post_api_request("/api/v1/auth/register", payload=creds)
    status_login, login_body = await make_post_api_request("/api/v1/auth/login", payload=creds)
    assert status_login == HTTPStatus.OK

    status_refresh, refresh_body = await make_post_api_request(
        "/api/v1/auth/refresh",
        payload={"refresh_token": login_body["refresh_token"]},
    )
    assert status_refresh == HTTPStatus.OK
    assert refresh_body["refresh_token"] != login_body["refresh_token"]

    status_reuse, _ = await make_post_api_request(
        "/api/v1/auth/refresh",
        payload={"refresh_token": login_body["refresh_token"]},
    )
    assert status_reuse == HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_auth_logout_all_invalidates_old_tokens(make_post_api_request, make_get_api_request):
    creds = {"login": "charlie", "password": "StrongPass123"}
    await make_post_api_request("/api/v1/auth/register", payload=creds)
    _, login_body = await make_post_api_request("/api/v1/auth/login", payload=creds)
    access_token = login_body["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    status, _ = await make_post_api_request("/api/v1/auth/logout-all", headers=headers)
    assert status == HTTPStatus.NO_CONTENT

    status_me, _ = await make_get_api_request("/api/v1/auth/me", headers=headers)
    assert status_me == HTTPStatus.UNAUTHORIZED
