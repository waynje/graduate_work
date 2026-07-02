from __future__ import annotations

from sqlalchemy import case, func, select

from ugc_service.db import session_scope
from ugc_service.models import MovieRating
from ugc_service.services.common import NotFoundError, ServiceValidationError, serialize_dt


def _validate_score(score: int) -> None:
    if not isinstance(score, int) or score < 0 or score > 10:
        raise ServiceValidationError("Field 'score' must be integer in range 0..10.")


def upsert_movie_rating(movie_id: str, user_id: str, score: int) -> dict:
    _validate_score(score)
    with session_scope() as session:
        rating = session.scalar(
            select(MovieRating).where(
                MovieRating.user_id == user_id,
                MovieRating.movie_id == movie_id,
            )
        )
        if rating is None:
            rating = MovieRating(user_id=user_id, movie_id=movie_id, score=score)
            session.add(rating)
        else:
            rating.score = score
    return {"status": "ok", "movie_id": movie_id, "user_id": user_id, "score": score}


def delete_movie_rating(movie_id: str, user_id: str) -> None:
    with session_scope() as session:
        rating = session.scalar(
            select(MovieRating).where(
                MovieRating.user_id == user_id,
                MovieRating.movie_id == movie_id,
            )
        )
        if rating is None:
            raise NotFoundError("Rating not found.")
        session.delete(rating)


def movie_rating_stats(movie_id: str) -> dict:
    with session_scope() as session:
        stats = session.execute(
            select(
                func.count().label("ratings_count"),
                func.sum(case((MovieRating.score == 10, 1), else_=0)).label("likes_count"),
                func.sum(case((MovieRating.score == 0, 1), else_=0)).label("dislikes_count"),
                func.avg(MovieRating.score).label("avg_score"),
            ).where(MovieRating.movie_id == movie_id)
        ).one()

    return {
        "movie_id": movie_id,
        "ratings_count": int(stats.ratings_count or 0),
        "likes_count": int(stats.likes_count or 0),
        "dislikes_count": int(stats.dislikes_count or 0),
        "avg_score": float(stats.avg_score) if stats.avg_score is not None else None,
    }


def list_user_likes(user_id: str, limit: int, offset: int) -> dict:
    with session_scope() as session:
        rows = session.execute(
            select(MovieRating.movie_id, MovieRating.score, MovieRating.updated_at)
            .where(MovieRating.user_id == user_id, MovieRating.score == 10)
            .order_by(MovieRating.updated_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()

    return {
        "user_id": user_id,
        "items": [
            {
                "movie_id": row.movie_id,
                "score": row.score,
                "updated_at": serialize_dt(row.updated_at),
            }
            for row in rows
        ],
    }
