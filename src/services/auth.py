from __future__ import annotations

import json
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from urllib.parse import urlencode
from uuid import UUID, uuid4

import httpx
import psycopg
from fastapi import Depends, Header, HTTPException
from redis.asyncio import Redis

from core.config import Settings, get_settings
from core.decorators import backoff
from core.security import decode_token, hash_password, make_token, verify_password
from db.postgres import get_pg_connection
from db.redis import get_redis


DEFAULT_ROLE = "user"


class AuthService:
    def __init__(self, *, conn: psycopg.AsyncConnection, redis: Redis, settings: Settings) -> None:
        self.conn = conn
        self.redis = redis
        self.settings = settings

    async def register_user(self, *, login: str, password: str) -> dict[str, Any]:
        user_id = str(uuid4())
        password_hash = hash_password(password)
        try:
            async with self.conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO auth_users (id, login, password_hash)
                    VALUES (%s, %s, %s)
                    RETURNING id, login, is_active, is_superuser;
                    """,
                    (user_id, login, password_hash),
                )
                user = await cur.fetchone()
                await cur.execute(
                    """
                    INSERT INTO auth_user_roles (user_id, role_id)
                    SELECT %s, r.id
                    FROM auth_roles r
                    WHERE r.name = %s
                    ON CONFLICT DO NOTHING;
                    """,
                    (user_id, DEFAULT_ROLE),
                )
            await self.conn.commit()
            return {
                "id": str(user["id"]),
                "login": user["login"],
                "is_active": user["is_active"],
                "is_superuser": user["is_superuser"],
                "roles": [DEFAULT_ROLE],
            }
        except psycopg.errors.UniqueViolation:
            await self.conn.rollback()
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail="login already exists")

    async def authenticate_user(self, *, login: str, password: str, user_agent: str | None, ip: str | None) -> dict[str, str]:
        await self._ensure_login_not_rate_limited(login=login, ip=ip)
        async with self.conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, login, password_hash, is_active, token_version
                FROM auth_users
                WHERE login = %s;
                """,
                (login,),
            )
            user = await cur.fetchone()
            if not user or not verify_password(password, user["password_hash"]):
                await self._record_failed_login_attempt(login=login, ip=ip)
                raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="invalid credentials")
            if not user["is_active"]:
                raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="user is inactive")
        await self._clear_failed_login_attempts(login=login, ip=ip)
        roles = await self._get_roles_by_user_id(str(user["id"]))
        tokens = self._issue_token_pair(
            user_id=str(user["id"]),
            roles=roles,
            token_version=user["token_version"],
        )
        await self._persist_login_session(
            user_id=str(user["id"]),
            refresh_token=tokens["refresh_token"],
            user_agent=user_agent,
            ip=ip,
        )
        return tokens

    async def refresh(self, *, refresh_token: str, user_agent: str | None, ip: str | None) -> dict[str, str]:
        payload = self._decode_expected_token(refresh_token, expected_type="refresh")
        refresh_jti = payload["jti"]
        user_id = payload["sub"]
        if await self._is_blacklisted("refresh", refresh_jti):
            raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="refresh token revoked")

        async with self.conn.cursor() as cur:
            await cur.execute(
                """
                SELECT rt.revoked, rt.expires_at, u.token_version
                FROM auth_refresh_tokens rt
                JOIN auth_users u ON u.id = rt.user_id
                WHERE rt.jti = %s AND rt.user_id = %s;
                """,
                (refresh_jti, user_id),
            )
            token_row = await cur.fetchone()
            if not token_row or token_row["revoked"]:
                raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="refresh token revoked")
            if token_row["expires_at"] < datetime.now(timezone.utc):
                raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="refresh token expired")
            if payload.get("ver") != token_row["token_version"]:
                raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="token version mismatch")
        roles = await self._get_roles_by_user_id(user_id)
        tokens = self._issue_token_pair(
            user_id=user_id,
            roles=roles,
            token_version=token_row["token_version"],
        )

        async with self.conn.cursor() as cur:
            new_refresh_payload = decode_token(tokens["refresh_token"], self.settings)
            await cur.execute(
                "UPDATE auth_refresh_tokens SET revoked = TRUE WHERE jti = %s;",
                (refresh_jti,),
            )
            await cur.execute(
                """
                INSERT INTO auth_refresh_tokens (jti, user_id, expires_at, revoked, user_agent, ip)
                VALUES (%s, %s, %s, FALSE, %s, %s);
                """,
                (
                    new_refresh_payload["jti"],
                    user_id,
                    datetime.fromtimestamp(new_refresh_payload["exp"], tz=timezone.utc),
                    user_agent,
                    ip,
                ),
            )
        await self.conn.commit()
        await self._blacklist_jti("refresh", refresh_jti, payload["exp"])
        return tokens

    async def logout(self, *, access_payload: dict[str, Any], refresh_token: str) -> None:
        refresh_payload = self._decode_expected_token(refresh_token, expected_type="refresh")
        async with self.conn.cursor() as cur:
            await cur.execute(
                "UPDATE auth_refresh_tokens SET revoked = TRUE WHERE jti = %s AND user_id = %s;",
                (refresh_payload["jti"], access_payload["sub"]),
            )
        await self.conn.commit()
        await self._blacklist_jti("access", access_payload["jti"], access_payload["exp"])
        await self._blacklist_jti("refresh", refresh_payload["jti"], refresh_payload["exp"])

    async def logout_all(self, *, access_payload: dict[str, Any]) -> None:
        user_id = access_payload["sub"]
        async with self.conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE auth_users
                SET token_version = token_version + 1, updated_at = NOW()
                WHERE id = %s
                RETURNING token_version;
                """,
                (user_id,),
            )
            updated = await cur.fetchone()
            if not updated:
                raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="user not found")
            await cur.execute(
                "UPDATE auth_refresh_tokens SET revoked = TRUE WHERE user_id = %s;",
                (user_id,),
            )
        await self.conn.commit()
        await self._blacklist_jti("access", access_payload["jti"], access_payload["exp"])
        await self.redis.delete(self._roles_cache_key(user_id))

    async def update_me(self, *, user_id: str, login: str | None, password: str | None) -> dict[str, Any]:
        if not login and not password:
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="nothing to update")

        fields: list[str] = []
        params: list[Any] = []
        if login is not None:
            fields.append("login = %s")
            params.append(login)
        if password is not None:
            fields.append("password_hash = %s")
            params.append(hash_password(password))
        fields.append("updated_at = NOW()")
        params.append(user_id)
        query = f"""
            UPDATE auth_users
            SET {", ".join(fields)}
            WHERE id = %s
            RETURNING id, login, is_active, is_superuser;
        """
        try:
            async with self.conn.cursor() as cur:
                await cur.execute(query, params)
                row = await cur.fetchone()
                if not row:
                    raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="user not found")
            await self.conn.commit()
        except psycopg.errors.UniqueViolation:
            await self.conn.rollback()
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail="login already exists")
        roles = await self._get_roles_by_user_id(user_id)
        return {
            "id": str(row["id"]),
            "login": row["login"],
            "is_active": row["is_active"],
            "is_superuser": row["is_superuser"],
            "roles": roles,
        }

    async def get_login_history(self, *, user_id: str, limit: int, offset: int) -> list[dict[str, Any]]:
        async with self.conn.cursor() as cur:
            await cur.execute(
                """
                SELECT user_agent, ip, created_at
                FROM auth_login_history
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s;
                """,
                (user_id, limit, offset),
            )
            rows = await cur.fetchall()
        return [{"user_agent": row["user_agent"], "ip": row["ip"], "created_at": row["created_at"]} for row in rows]

    async def get_current_user(self, access_token: str) -> dict[str, Any]:
        payload = self._decode_expected_token(access_token, expected_type="access")
        if await self._is_blacklisted("access", payload["jti"]):
            raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="token revoked")

        async with self.conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, login, is_active, is_superuser, token_version
                FROM auth_users
                WHERE id = %s;
                """,
                (payload["sub"],),
            )
            user = await cur.fetchone()
            if not user or not user["is_active"]:
                raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="user is inactive or not found")
            if payload.get("ver") != user["token_version"]:
                raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="token version mismatch")

        roles = await self._get_roles_by_user_id(str(user["id"]))
        return {
            "id": str(user["id"]),
            "login": user["login"],
            "is_active": user["is_active"],
            "is_superuser": user["is_superuser"],
            "roles": roles,
            "payload": payload,
        }

    async def create_role(self, *, name: str, description: str) -> dict[str, Any]:
        role_id = str(uuid4())
        try:
            async with self.conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO auth_roles (id, name, description)
                    VALUES (%s, %s, %s)
                    RETURNING id, name, description;
                    """,
                    (role_id, name, description),
                )
                row = await cur.fetchone()
            await self.conn.commit()
            return {"id": str(row["id"]), "name": row["name"], "description": row["description"]}
        except psycopg.errors.UniqueViolation:
            await self.conn.rollback()
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail="role already exists")

    async def list_roles(self) -> list[dict[str, Any]]:
        async with self.conn.cursor() as cur:
            await cur.execute("SELECT id, name, description FROM auth_roles ORDER BY name;")
            rows = await cur.fetchall()
        return [{"id": str(r["id"]), "name": r["name"], "description": r["description"]} for r in rows]

    async def update_role(self, *, role_id: str, name: str | None, description: str | None) -> dict[str, Any]:
        if name is None and description is None:
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="nothing to update")
        fields: list[str] = []
        params: list[Any] = []
        if name is not None:
            fields.append("name = %s")
            params.append(name)
        if description is not None:
            fields.append("description = %s")
            params.append(description)
        params.append(role_id)
        query = f"""
            UPDATE auth_roles
            SET {", ".join(fields)}
            WHERE id = %s
            RETURNING id, name, description;
        """
        try:
            async with self.conn.cursor() as cur:
                await cur.execute(query, params)
                row = await cur.fetchone()
                if not row:
                    raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="role not found")
            await self.conn.commit()
            return {"id": str(row["id"]), "name": row["name"], "description": row["description"]}
        except psycopg.errors.UniqueViolation:
            await self.conn.rollback()
            raise HTTPException(status_code=HTTPStatus.CONFLICT, detail="role already exists")

    async def delete_role(self, *, role_id: str) -> None:
        async with self.conn.cursor() as cur:
            await cur.execute("DELETE FROM auth_roles WHERE id = %s;", (role_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="role not found")
        await self.conn.commit()

    async def grant_role(self, *, user_id: str, role_id: str) -> None:
        async with self.conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO auth_user_roles (user_id, role_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING;
                """,
                (user_id, role_id),
            )
        await self.conn.commit()
        await self.redis.delete(self._roles_cache_key(user_id))

    async def revoke_role(self, *, user_id: str, role_id: str) -> None:
        async with self.conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM auth_user_roles WHERE user_id = %s AND role_id = %s;",
                (user_id, role_id),
            )
        await self.conn.commit()
        await self.redis.delete(self._roles_cache_key(user_id))

    async def check_role(self, *, user_id: str, required_role: str) -> bool:
        roles = await self._get_roles_by_user_id(user_id)
        return required_role in roles

    async def ensure_superuser(self) -> None:
        if not self.settings.auth_superuser_login or not self.settings.auth_superuser_password:
            return
        async with self.conn.cursor() as cur:
            await cur.execute(
                "SELECT id FROM auth_users WHERE login = %s;",
                (self.settings.auth_superuser_login,),
            )
            existing = await cur.fetchone()
            if existing:
                return
            user_id = str(uuid4())
            await cur.execute(
                """
                INSERT INTO auth_users (id, login, password_hash, is_superuser)
                VALUES (%s, %s, %s, TRUE);
                """,
                (user_id, self.settings.auth_superuser_login, hash_password(self.settings.auth_superuser_password)),
            )
            await cur.execute(
                """
                INSERT INTO auth_user_roles (user_id, role_id)
                SELECT %s, id FROM auth_roles WHERE name IN ('user', 'admin')
                ON CONFLICT DO NOTHING;
                """,
                (user_id,),
            )
        await self.conn.commit()

    async def get_google_login_url(self) -> dict[str, str]:
        self._ensure_google_oauth_configured()
        state = str(uuid4())
        await self.redis.set(
            self._google_oauth_state_key(state),
            "1",
            ex=self.settings.auth_google_oauth_state_ttl_seconds,
        )
        query = urlencode(
            {
                "client_id": self.settings.auth_google_client_id,
                "redirect_uri": self.settings.auth_google_redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
            }
        )
        authorization_url = f"{self.settings.auth_google_authorize_url}?{query}"
        return {"authorization_url": authorization_url, "state": state, "provider": "google"}

    async def authenticate_google_user(
        self,
        *,
        code: str,
        state: str,
        user_agent: str | None,
        ip: str | None,
    ) -> dict[str, str]:
        self._ensure_google_oauth_configured()
        is_state_valid = await self._consume_google_oauth_state(state)
        if not is_state_valid:
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="invalid oauth state")

        try:
            token_payload = await self._exchange_google_code(code)
            google_profile = await self._get_google_userinfo(token_payload["access_token"])
        except httpx.HTTPError:
            raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail="google oauth is temporarily unavailable")

        user = await self._get_or_create_google_user(
            google_sub=google_profile["sub"],
            email=google_profile.get("email"),
        )
        roles = await self._get_roles_by_user_id(str(user["id"]))
        tokens = self._issue_token_pair(
            user_id=str(user["id"]),
            roles=roles,
            token_version=user["token_version"],
        )
        await self._persist_login_session(
            user_id=str(user["id"]),
            refresh_token=tokens["refresh_token"],
            user_agent=user_agent,
            ip=ip,
        )
        return tokens

    def _ensure_google_oauth_configured(self) -> None:
        if not (
            self.settings.auth_google_client_id
            and self.settings.auth_google_client_secret
            and self.settings.auth_google_redirect_uri
        ):
            raise HTTPException(status_code=HTTPStatus.SERVICE_UNAVAILABLE, detail="google oauth is not configured")

    def _google_oauth_state_key(self, state: str) -> str:
        return f"auth:oauth:google:state:{state}"

    async def _consume_google_oauth_state(self, state: str) -> bool:
        key = self._google_oauth_state_key(state)
        state_exists = await self.redis.exists(key)
        if state_exists:
            await self.redis.delete(key)
        return bool(state_exists)

    @backoff(start_sleep_time=0.2, factor=2, border_sleep_time=3, max_retries=3)
    async def _exchange_google_code(self, code: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                self.settings.auth_google_token_url,
                data={
                    "code": code,
                    "client_id": self.settings.auth_google_client_id,
                    "client_secret": self.settings.auth_google_client_secret,
                    "redirect_uri": self.settings.auth_google_redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if response.status_code >= 400:
                raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="google token exchange failed")
            payload = response.json()
        if "access_token" not in payload:
            raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="google did not return access token")
        return payload

    @backoff(start_sleep_time=0.2, factor=2, border_sleep_time=3, max_retries=3)
    async def _get_google_userinfo(self, access_token: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                self.settings.auth_google_userinfo_url,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if response.status_code >= 400:
                raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="google userinfo request failed")
            payload = response.json()
        if "sub" not in payload:
            raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="google user profile is invalid")
        return payload

    async def _get_or_create_google_user(self, *, google_sub: str, email: str | None) -> dict[str, Any]:
        async with self.conn.cursor() as cur:
            await cur.execute(
                """
                SELECT u.id, u.login, u.is_active, u.is_superuser, u.token_version
                FROM auth_social_accounts sa
                JOIN auth_users u ON u.id = sa.user_id
                WHERE sa.provider = 'google' AND sa.social_id = %s;
                """,
                (google_sub,),
            )
            existing = await cur.fetchone()
            if existing:
                return existing

            user = None
            if email:
                await cur.execute(
                    """
                    SELECT id, login, is_active, is_superuser, token_version
                    FROM auth_users
                    WHERE login = %s;
                    """,
                    (email,),
                )
                user = await cur.fetchone()

            if not user:
                user_id = str(uuid4())
                login = await self._build_unique_social_login(
                    cur=cur,
                    base_login=email or f"google_{google_sub[:10]}",
                )
                await cur.execute(
                    """
                    INSERT INTO auth_users (id, login, password_hash)
                    VALUES (%s, %s, %s)
                    RETURNING id, login, is_active, is_superuser, token_version;
                    """,
                    (user_id, login, hash_password(str(uuid4()))),
                )
                user = await cur.fetchone()
                await cur.execute(
                    """
                    INSERT INTO auth_user_roles (user_id, role_id)
                    SELECT %s, r.id
                    FROM auth_roles r
                    WHERE r.name = %s
                    ON CONFLICT DO NOTHING;
                    """,
                    (user_id, DEFAULT_ROLE),
                )

            await cur.execute(
                """
                INSERT INTO auth_social_accounts (id, user_id, provider, social_id, email)
                VALUES (%s, %s, 'google', %s, %s)
                ON CONFLICT (provider, social_id) DO NOTHING;
                """,
                (str(uuid4()), str(user["id"]), google_sub, email),
            )
        await self.conn.commit()
        return user

    async def _build_unique_social_login(self, *, cur: psycopg.AsyncCursor[Any], base_login: str) -> str:
        login_candidate = base_login
        suffix = 0
        while True:
            await cur.execute("SELECT 1 FROM auth_users WHERE login = %s;", (login_candidate,))
            exists = await cur.fetchone()
            if not exists:
                return login_candidate
            suffix += 1
            login_candidate = f"{base_login}_{suffix}"

    async def _persist_login_session(
        self,
        *,
        user_id: str,
        refresh_token: str,
        user_agent: str | None,
        ip: str | None,
    ) -> None:
        payload = decode_token(refresh_token, self.settings)
        async with self.conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO auth_refresh_tokens (jti, user_id, expires_at, revoked, user_agent, ip)
                VALUES (%s, %s, %s, FALSE, %s, %s);
                """,
                (payload["jti"], user_id, datetime.fromtimestamp(payload["exp"], tz=timezone.utc), user_agent, ip),
            )
            await cur.execute(
                """
                INSERT INTO auth_login_history (user_id, user_agent, ip)
                VALUES (%s, %s, %s);
                """,
                (user_id, user_agent, ip),
            )
        await self.conn.commit()

    def _issue_token_pair(self, *, user_id: str, roles: list[str], token_version: int) -> dict[str, str]:
        access, _, _ = make_token(
            user_id=user_id,
            token_type="access",
            ttl_seconds=self.settings.auth_access_token_ttl_seconds,
            secret=self.settings.auth_jwt_secret,
            algorithm=self.settings.auth_jwt_algorithm,
            roles=roles,
            token_version=token_version,
            issuer=self.settings.auth_jwt_issuer,
            audience=self.settings.auth_jwt_audience,
        )
        refresh, _, _ = make_token(
            user_id=user_id,
            token_type="refresh",
            ttl_seconds=self.settings.auth_refresh_token_ttl_seconds,
            secret=self.settings.auth_jwt_secret,
            algorithm=self.settings.auth_jwt_algorithm,
            roles=roles,
            token_version=token_version,
            issuer=self.settings.auth_jwt_issuer,
            audience=self.settings.auth_jwt_audience,
        )
        return {"access_token": access, "refresh_token": refresh, "token_type": "bearer"}

    def _decode_expected_token(self, token: str, *, expected_type: str) -> dict[str, Any]:
        try:
            payload = decode_token(token, self.settings)
        except Exception:
            raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="invalid token")
        if payload.get("token_type") != expected_type:
            raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail=f"invalid token type, expected {expected_type}")
        return payload

    def _roles_cache_key(self, user_id: str) -> str:
        return f"auth:user_roles:{user_id}"

    def _blacklist_key(self, token_type: str, jti: str) -> str:
        return f"auth:blacklist:{token_type}:{jti}"

    async def _get_roles_by_user_id(self, user_id: str) -> list[str]:
        cache_key = self._roles_cache_key(user_id)
        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached)
        async with self.conn.cursor() as cur:
            await cur.execute(
                """
                SELECT r.name
                FROM auth_roles r
                JOIN auth_user_roles ur ON ur.role_id = r.id
                WHERE ur.user_id = %s
                ORDER BY r.name;
                """,
                (user_id,),
            )
            rows = await cur.fetchall()
        roles = [row["name"] for row in rows]
        await self.redis.set(cache_key, json.dumps(roles), ex=self.settings.auth_roles_cache_ttl_seconds)
        return roles

    async def _is_blacklisted(self, token_type: str, jti: str) -> bool:
        return bool(await self.redis.exists(self._blacklist_key(token_type, jti)))

    async def _blacklist_jti(self, token_type: str, jti: str, exp_ts: int) -> None:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        ttl = max(exp_ts - now_ts, 1)
        await self.redis.set(self._blacklist_key(token_type, jti), "1", ex=ttl)

    def _login_attempts_key(self, login: str, ip: str | None) -> str:
        ip_value = ip or "unknown-ip"
        return f"auth:login_attempts:{ip_value}:{login}"

    async def _ensure_login_not_rate_limited(self, *, login: str, ip: str | None) -> None:
        key = self._login_attempts_key(login, ip)
        attempts = await self.redis.get(key)
        if attempts and int(attempts) >= self.settings.auth_login_rate_limit_attempts:
            raise HTTPException(status_code=HTTPStatus.TOO_MANY_REQUESTS, detail="too many login attempts")

    async def _record_failed_login_attempt(self, *, login: str, ip: str | None) -> None:
        key = self._login_attempts_key(login, ip)
        attempts = await self.redis.incr(key)
        if attempts == 1:
            await self.redis.expire(key, self.settings.auth_login_rate_limit_window_seconds)

    async def _clear_failed_login_attempts(self, *, login: str, ip: str | None) -> None:
        key = self._login_attempts_key(login, ip)
        await self.redis.delete(key)


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="missing Authorization header")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="invalid authorization scheme")
    return parts[1]


def get_auth_service(
    conn: psycopg.AsyncConnection = Depends(get_pg_connection),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> AuthService:
    return AuthService(conn=conn, redis=redis, settings=settings)


async def get_current_user(
    authorization: str | None = Header(default=None),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    token = _extract_bearer_token(authorization)
    return await service.get_current_user(token)


async def require_admin(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if not (current_user.get("is_superuser") or "admin" in current_user.get("roles", [])):
        raise HTTPException(status_code=HTTPStatus.FORBIDDEN, detail="admin role required")
    return current_user


