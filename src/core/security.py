import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import jwt

from core.config import Settings


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def hash_password(password: str, *, iterations: int = 600_000) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${_b64url(salt)}${_b64url(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64 + "=" * (-len(salt_b64) % 4))
        digest = base64.urlsafe_b64decode(digest_b64 + "=" * (-len(digest_b64) % 4))
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(candidate, digest)
    except Exception:
        return False


def make_token(
    *,
    user_id: str,
    token_type: str,
    ttl_seconds: int,
    secret: str,
    algorithm: str,
    roles: list[str],
    token_version: int,
    issuer: str,
    audience: str,
) -> tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl_seconds)
    jti = str(uuid4())
    payload: dict[str, Any] = {
        "sub": user_id,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "token_type": token_type,
        "roles": roles,
        "ver": token_version,
        "iss": issuer,
        "aud": audience,
    }
    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token, jti, expires_at


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.auth_jwt_secret,
        algorithms=[settings.auth_jwt_algorithm],
        issuer=settings.auth_jwt_issuer,
        audience=settings.auth_jwt_audience,
        options={"require": ["exp", "iat", "sub", "jti", "iss", "aud"]},
    )
