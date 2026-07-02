from __future__ import annotations

from sqlalchemy import select

from ugc_service.db import session_scope
from ugc_service.models import UserBookmark
from ugc_service.services.common import NotFoundError, serialize_dt


def add_bookmark(movie_id: str, user_id: str) -> None:
    with session_scope() as session:
        row = session.scalar(
            select(UserBookmark).where(
                UserBookmark.user_id == user_id,
                UserBookmark.movie_id == movie_id,
            )
        )
        if row is None:
            session.add(UserBookmark(user_id=user_id, movie_id=movie_id))


def delete_bookmark(movie_id: str, user_id: str) -> None:
    with session_scope() as session:
        row = session.scalar(
            select(UserBookmark).where(
                UserBookmark.user_id == user_id,
                UserBookmark.movie_id == movie_id,
            )
        )
        if row is None:
            raise NotFoundError("Bookmark not found.")
        session.delete(row)


def list_bookmarks(user_id: str) -> dict:
    with session_scope() as session:
        rows = session.execute(
            select(UserBookmark.movie_id, UserBookmark.created_at)
            .where(UserBookmark.user_id == user_id)
            .order_by(UserBookmark.created_at.desc())
        ).all()

    return {
        "user_id": user_id,
        "items": [
            {"movie_id": row.movie_id, "created_at": serialize_dt(row.created_at)}
            for row in rows
        ],
    }
