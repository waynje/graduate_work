import http
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import Settings, get_settings
from core.security import decode_token


def decode_jwt_token(token: str, settings: Settings) -> dict[str, Any] | None:
    try:
        return decode_token(token, settings)
    except Exception:
        return None


class JWTBearer(HTTPBearer):
    def __init__(self, settings: Settings, auto_error: bool = True):
        super().__init__(auto_error=auto_error)
        self.settings = settings

    async def __call__(self, request: Request) -> dict[str, Any]:
        credentials: HTTPAuthorizationCredentials = await super().__call__(request)
        if not credentials:
            raise HTTPException(status_code=http.HTTPStatus.FORBIDDEN, detail="Invalid authorization code.")
        if credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=http.HTTPStatus.UNAUTHORIZED, detail="Only Bearer token might be accepted")
        decoded_token = self.parse_token(credentials.credentials)
        if not decoded_token:
            raise HTTPException(status_code=http.HTTPStatus.FORBIDDEN, detail="Invalid or expired token.")
        return decoded_token

    def parse_token(self, jwt_token: str) -> dict[str, Any] | None:
        return decode_jwt_token(jwt_token, self.settings)


bearer_scheme = HTTPBearer(auto_error=True)


async def get_jwt_bearer(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    checker = JWTBearer(settings=settings)
    if not credentials:
        raise HTTPException(status_code=http.HTTPStatus.FORBIDDEN, detail="Invalid authorization code.")
    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=http.HTTPStatus.UNAUTHORIZED, detail="Only Bearer token might be accepted")
    payload = checker.parse_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=http.HTTPStatus.FORBIDDEN, detail="Invalid or expired token.")
    return payload
