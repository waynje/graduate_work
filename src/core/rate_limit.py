from collections.abc import Sequence
from http import HTTPStatus

from fastapi import Request
from fastapi.responses import ORJSONResponse
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware

from db import redis


class RedisRateLimiterMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        requests_limit: int,
        window_seconds: int,
        exempt_path_prefixes: Sequence[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.requests_limit = requests_limit
        self.window_seconds = window_seconds
        self.exempt_path_prefixes = tuple(exempt_path_prefixes or ())

    async def dispatch(self, request: Request, call_next):
        if any(request.url.path.startswith(prefix) for prefix in self.exempt_path_prefixes):
            return await call_next(request)

        if not redis.redis:
            return await call_next(request)

        ip = request.headers.get("X-Forwarded-For") or (request.client.host if request.client else "unknown")
        key = f"api:rate_limit:{ip}:{request.url.path}"
        try:
            requests_count = await redis.redis.incr(key)
            if requests_count == 1:
                await redis.redis.expire(key, self.window_seconds)
            if requests_count > self.requests_limit:
                return ORJSONResponse(
                    status_code=HTTPStatus.TOO_MANY_REQUESTS,
                    content={"detail": "too many requests"},
                )
        except RedisError:
            # Graceful degradation: if limiter storage is unavailable, keep serving requests.
            return await call_next(request)

        return await call_next(request)
