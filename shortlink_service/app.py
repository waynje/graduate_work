from __future__ import annotations

import hashlib
import string
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from shortlink_service.db import ensure_tables, get_session_factory, init_engine
from shortlink_service.models import ShortLink


BASE62_ALPHABET = string.digits + string.ascii_letters


class ShortenPayload(BaseModel):
    target_url: str = Field(min_length=5, max_length=2048)


def _base62(number: int) -> str:
    if number == 0:
        return BASE62_ALPHABET[0]
    chars: list[str] = []
    while number > 0:
        number, remainder = divmod(number, len(BASE62_ALPHABET))
        chars.append(BASE62_ALPHABET[remainder])
    return "".join(reversed(chars))


def _build_code(target_url: str) -> str:
    digest = hashlib.sha256(target_url.encode("utf-8")).digest()
    as_int = int.from_bytes(digest[:8], "big")
    return _base62(as_int)[:8]


def _validate_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="target_url must be valid http(s) URL.")


def create_app() -> FastAPI:
    init_engine("sqlite+pysqlite:///./shortlink.db")
    ensure_tables()
    app = FastAPI(title="shortlink-service", version="1.0.0")
    session_factory = get_session_factory()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/v1/short-links")
    def create_short_link(payload: ShortenPayload) -> dict:
        _validate_http_url(payload.target_url)
        with session_factory() as session:
            existing = session.scalar(select(ShortLink).where(ShortLink.target_url == payload.target_url))
            if existing is not None:
                return {
                    "status": "ok",
                    "code": existing.code,
                    "target_url": existing.target_url,
                    "short_url": f"http://localhost:8020/s/{existing.code}",
                }
            code = _build_code(payload.target_url)
            row = ShortLink(code=code, target_url=payload.target_url)
            session.add(row)
            session.commit()
            return {
                "status": "ok",
                "code": code,
                "target_url": payload.target_url,
                "short_url": f"http://localhost:8020/s/{code}",
            }

    @app.get("/s/{code}")
    def resolve_short_link(code: str):
        with session_factory() as session:
            row = session.scalar(select(ShortLink).where(ShortLink.code == code))
            if row is None:
                raise HTTPException(status_code=404, detail="Short link not found.")
            return RedirectResponse(url=row.target_url, status_code=307)

    return app


app = create_app()
