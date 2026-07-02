from uuid import uuid4

from fastapi import Request
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware


class RequestIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, header_name: str = "X-Request-Id") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get(self.header_name) or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[self.header_name] = request_id

        span = trace.get_current_span()
        if span is not None:
            span.set_attribute("http.request_id", request_id)
        return response
