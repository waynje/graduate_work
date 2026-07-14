from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Protocol

import psycopg
from redis.asyncio import Redis

from models.film import Film
from services.recommendation_logic import (
    MovieInteraction,
    RecommendationResult,
    UserSignals,
    build_genre_weights,
    page_view_weight,
    parse_movie_id_from_url,
    rating_weight,
    recency_boost,
    score_candidates,
)

MOVIE_ID_SQL_PATTERN = (
    r"/movies/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


class RecommendationStorage(Protocol):
    async def recommend(
        self,
        *,
        genre_ids: list[str],
        genre_weights: dict[str, float],
        exclude_ids: list[str],
        limit: int,
    ) -> list[Film]:
        ...

    async def get_by_ids(self, movie_ids: list[str]) -> dict[str, Film]:
        ...

    async def get_popular(self, *, exclude_ids: list[str], limit: int) -> list[Film]:
        ...


class RecommendationRepository:
    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self._conn = conn

    async def load_signals_version(self, user_id: str) -> str:
        """Fingerprint of latest UGC activity so Redis cache keys change when signals change."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT GREATEST(
                    COALESCE(
                        (
                            SELECT MAX(occurred_at)
                            FROM ugc_events
                            WHERE user_id = %s AND event_type = 'page_view'
                        ),
                        TIMESTAMPTZ 'epoch'
                    ),
                    COALESCE(
                        (SELECT MAX(updated_at) FROM movie_ratings WHERE user_id = %s),
                        TIMESTAMPTZ 'epoch'
                    ),
                    COALESCE(
                        (SELECT MAX(created_at) FROM user_bookmarks WHERE user_id = %s),
                        TIMESTAMPTZ 'epoch'
                    )
                ) AS signals_version
                """,
                (user_id, user_id, user_id),
            )
            row = await cur.fetchone()

        version = row["signals_version"] if row else None
        if version is None:
            return "0"
        if isinstance(version, datetime):
            if version.tzinfo is None:
                version = version.replace(tzinfo=timezone.utc)
            return version.isoformat()
        return str(version)

    async def load_user_signals(self, user_id: str) -> UserSignals:
        interactions: list[MovieInteraction] = []

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT page_url, duration_ms, occurred_at
                FROM ugc_events
                WHERE user_id = %s AND event_type = 'page_view'
                ORDER BY occurred_at DESC
                LIMIT 200
                """,
                (user_id,),
            )
            page_views = await cur.fetchall()

            await cur.execute(
                """
                SELECT movie_id, score
                FROM movie_ratings
                WHERE user_id = %s AND score >= 7
                ORDER BY updated_at DESC
                LIMIT 100
                """,
                (user_id,),
            )
            ratings = await cur.fetchall()

            await cur.execute(
                """
                SELECT movie_id
                FROM user_bookmarks
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 100
                """,
                (user_id,),
            )
            bookmarks = await cur.fetchall()

        for row in page_views:
            movie_id = parse_movie_id_from_url(row["page_url"])
            if not movie_id:
                continue
            weight = page_view_weight(row["duration_ms"]) + recency_boost(row["occurred_at"])
            interactions.append(MovieInteraction(movie_id=movie_id, weight=weight, source="page_view"))

        for row in ratings:
            interactions.append(
                MovieInteraction(
                    movie_id=row["movie_id"],
                    weight=rating_weight(row["score"]),
                    source="rating",
                )
            )

        for row in bookmarks:
            interactions.append(
                MovieInteraction(
                    movie_id=row["movie_id"],
                    weight=2.5,
                    source="bookmark",
                )
            )

        return UserSignals(interactions=interactions)

    async def load_viewing_history(self, user_id: str, *, limit: int = 50) -> list[dict]:
        # Deduplicate by movie_id in SQL before applying LIMIT so repeats don't shrink the page.
        async with self._conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT movie_id, duration_ms, occurred_at
                FROM (
                    SELECT DISTINCT ON (movie_id)
                        movie_id,
                        duration_ms,
                        occurred_at
                    FROM (
                        SELECT
                            substring(page_url from %s) AS movie_id,
                            duration_ms,
                            occurred_at
                        FROM ugc_events
                        WHERE user_id = %s AND event_type = 'page_view'
                    ) extracted
                    WHERE movie_id IS NOT NULL
                    ORDER BY movie_id, occurred_at DESC
                ) unique_movies
                ORDER BY occurred_at DESC
                LIMIT %s
                """,
                (MOVIE_ID_SQL_PATTERN, user_id, limit),
            )
            rows = await cur.fetchall()

        return [
            {
                "movie_id": row["movie_id"],
                "duration_ms": row["duration_ms"],
                "occurred_at": row["occurred_at"].isoformat() if row["occurred_at"] else None,
            }
            for row in rows
        ]


class RecommendationCache:
    def __init__(self, redis: Redis, expire_seconds: int) -> None:
        self._redis = redis
        self._expire_seconds = expire_seconds

    def _key(self, user_id: str, limit: int, signals_version: str) -> str:
        return f"recommendations:{user_id}:{limit}:{signals_version}"

    async def get(
        self,
        user_id: str,
        limit: int,
        signals_version: str,
    ) -> list[RecommendationResult] | None:
        raw = await self._redis.get(self._key(user_id, limit, signals_version))
        if not raw:
            return None
        payload = json.loads(raw)
        return [
            RecommendationResult(
                film=Film.model_validate(item["film"]),
                score=item["score"],
                reason=item["reason"],
            )
            for item in payload
        ]

    async def set(
        self,
        user_id: str,
        limit: int,
        signals_version: str,
        items: list[RecommendationResult],
    ) -> None:
        payload = [
            {"film": item.film.model_dump(), "score": item.score, "reason": item.reason}
            for item in items
        ]
        await self._redis.set(
            self._key(user_id, limit, signals_version),
            json.dumps(payload),
            ex=self._expire_seconds,
        )


class RecommendationService:
    def __init__(
        self,
        repository: RecommendationRepository,
        storage: RecommendationStorage,
        cache: RecommendationCache,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._cache = cache

    async def get_recommendations(self, user_id: str, *, limit: int = 20) -> list[RecommendationResult]:
        signals_version = await self._repository.load_signals_version(user_id)
        cached = await self._cache.get(user_id, limit, signals_version)
        if cached is not None:
            return cached

        signals = await self._repository.load_user_signals(user_id)
        exclude_ids = list(signals.movie_ids)
        movie_weights = signals.movie_weights

        if not movie_weights:
            popular = await self._storage.get_popular(exclude_ids=exclude_ids, limit=limit)
            results = [
                RecommendationResult(film=film, score=film.imdb_rating or 0.0, reason="popular")
                for film in popular
            ]
            await self._cache.set(user_id, limit, signals_version, results)
            return results

        known_films = await self._storage.get_by_ids(list(movie_weights.keys()))
        genre_weights = build_genre_weights(movie_weights, known_films)

        if genre_weights:
            top_genres = [
                genre_id
                for genre_id, _ in sorted(genre_weights.items(), key=lambda item: item[1], reverse=True)[:5]
            ]
            weighted = {genre_id: genre_weights[genre_id] for genre_id in top_genres}
            candidates = await self._storage.recommend(
                genre_ids=top_genres,
                genre_weights=weighted,
                exclude_ids=exclude_ids,
                limit=max(limit * 3, 30),
            )
            results = score_candidates(candidates, genre_weights, reason="genre_match")
        else:
            candidates = await self._storage.get_popular(exclude_ids=exclude_ids, limit=limit * 2)
            results = [
                RecommendationResult(film=film, score=film.imdb_rating or 0.0, reason="popular")
                for film in candidates
            ]

        results = results[:limit]
        if len(results) < limit:
            popular = await self._storage.get_popular(
                exclude_ids=exclude_ids + [item.film.id for item in results],
                limit=limit - len(results),
            )
            results.extend(
                RecommendationResult(film=film, score=film.imdb_rating or 0.0, reason="popular")
                for film in popular
            )

        await self._cache.set(user_id, limit, signals_version, results)
        return results

    async def get_viewing_history(self, user_id: str, *, limit: int = 50) -> list[dict]:
        return await self._repository.load_viewing_history(user_id, limit=limit)
