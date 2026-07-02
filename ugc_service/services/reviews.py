from __future__ import annotations

import uuid

from sqlalchemy import case, func, select

from ugc_service.db import session_scope
from ugc_service.models import MovieReview, ReviewVote
from ugc_service.services.common import NotFoundError, ServiceValidationError, serialize_dt

SUPPORTED_REVIEW_SORTS = {"created_asc", "created_desc", "score_desc", "helpful_desc"}


def add_review(movie_id: str, user_id: str, review_text: str, movie_score: int | None) -> str:
    if not isinstance(review_text, str) or not review_text.strip():
        raise ServiceValidationError("Field 'review_text' must be a non-empty string.")
    if movie_score is not None and (
        not isinstance(movie_score, int) or movie_score < 0 or movie_score > 10
    ):
        raise ServiceValidationError("Field 'movie_score' must be integer in range 0..10.")

    review_id = str(uuid.uuid4())
    with session_scope() as session:
        session.add(
            MovieReview(
                id=review_id,
                movie_id=movie_id,
                user_id=user_id,
                review_text=review_text.strip(),
                movie_score=movie_score,
            )
        )
    return review_id


def vote_review(review_id: str, user_id: str, vote_name: str) -> None:
    vote_map = {"like": 1, "dislike": -1}
    if vote_name not in vote_map:
        raise ServiceValidationError("Field 'vote' must be 'like' or 'dislike'.")
    vote = vote_map[vote_name]

    with session_scope() as session:
        review = session.scalar(select(MovieReview).where(MovieReview.id == review_id))
        if review is None:
            raise NotFoundError("Review not found.")

        review_vote = session.scalar(
            select(ReviewVote).where(
                ReviewVote.user_id == user_id,
                ReviewVote.review_id == review_id,
            )
        )
        if review_vote is None:
            review_vote = ReviewVote(user_id=user_id, review_id=review_id, vote=vote)
            session.add(review_vote)
        else:
            review_vote.vote = vote


def list_reviews(movie_id: str, sort: str, limit: int, offset: int) -> dict:
    if sort not in SUPPORTED_REVIEW_SORTS:
        raise ServiceValidationError("Unsupported sort mode.")

    likes_count = func.sum(case((ReviewVote.vote == 1, 1), else_=0))
    dislikes_count = func.sum(case((ReviewVote.vote == -1, 1), else_=0))
    helpful_score = likes_count - dislikes_count

    with session_scope() as session:
        query = (
            select(
                MovieReview.id,
                MovieReview.user_id,
                MovieReview.review_text,
                MovieReview.movie_score,
                MovieReview.created_at,
                likes_count.label("likes_count"),
                dislikes_count.label("dislikes_count"),
                helpful_score.label("helpful_score"),
            )
            .outerjoin(ReviewVote, ReviewVote.review_id == MovieReview.id)
            .where(MovieReview.movie_id == movie_id)
            .group_by(
                MovieReview.id,
                MovieReview.user_id,
                MovieReview.review_text,
                MovieReview.movie_score,
                MovieReview.created_at,
            )
        )

        if sort == "created_asc":
            query = query.order_by(MovieReview.created_at.asc())
        elif sort == "created_desc":
            query = query.order_by(MovieReview.created_at.desc())
        elif sort == "score_desc":
            query = query.order_by(MovieReview.movie_score.desc().nullslast(), MovieReview.created_at.desc())
        else:
            query = query.order_by(helpful_score.desc(), MovieReview.created_at.desc())

        rows = session.execute(query.limit(limit).offset(offset)).all()

    return {
        "movie_id": movie_id,
        "sort": sort,
        "items": [
            {
                "review_id": row.id,
                "user_id": row.user_id,
                "review_text": row.review_text,
                "movie_score": row.movie_score,
                "created_at": serialize_dt(row.created_at),
                "likes_count": int(row.likes_count or 0),
                "dislikes_count": int(row.dislikes_count or 0),
                "helpful_score": int(row.helpful_score or 0),
            }
            for row in rows
        ],
    }
