from __future__ import annotations

from datetime import datetime, timezone

import pytest

from models.film import Film
from services.recommendation_service import RecommendationService
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


class FakeStorage:
    def __init__(self) -> None:
        self.films: dict[str, Film] = {}
        self.popular: list[Film] = []
        self.recommend_result: list[Film] = []

    async def get_by_ids(self, movie_ids: list[str]) -> dict[str, Film]:
        return {movie_id: self.films[movie_id] for movie_id in movie_ids if movie_id in self.films}

    async def recommend(
        self,
        *,
        genre_ids: list[str],
        exclude_ids: list[str],
        limit: int,
    ) -> list[Film]:
        return self.recommend_result[:limit]

    async def get_popular(self, *, exclude_ids: list[str], limit: int) -> list[Film]:
        exclude = set(exclude_ids)
        return [film for film in self.popular if film.id not in exclude][:limit]


class FakeRepository:
    def __init__(self, signals: UserSignals, history: list[dict] | None = None) -> None:
        self.signals = signals
        self.history = history or []

    async def load_user_signals(self, user_id: str) -> UserSignals:
        return self.signals

    async def load_viewing_history(self, user_id: str, *, limit: int = 50) -> list[dict]:
        return self.history[:limit]


class FakeCache:
    def __init__(self) -> None:
        self.items: dict[tuple[str, int], list[RecommendationResult]] = {}

    async def get(self, user_id: str, limit: int) -> list[RecommendationResult] | None:
        return self.items.get((user_id, limit))

    async def set(self, user_id: str, limit: int, items: list[RecommendationResult]) -> None:
        self.items[(user_id, limit)] = items


@pytest.mark.parametrize(
    "page_url,expected",
    [
        ("/movies/550e8400-e29b-41d4-a716-446655440000", "550e8400-e29b-41d4-a716-446655440000"),
        ("https://movies.local/movies/550e8400-e29b-41d4-a716-446655440000/details", "550e8400-e29b-41d4-a716-446655440000"),
        ("/main", None),
        (None, None),
    ],
)
def test_parse_movie_id_from_url(page_url, expected):
    assert parse_movie_id_from_url(page_url) == expected


def test_page_view_weight_scales_with_duration():
    assert page_view_weight(None) == 1.0
    assert page_view_weight(30_000) == 1.5
    assert page_view_weight(300_000) == 3.0


def test_rating_weight_thresholds():
    assert rating_weight(10) == 3.0
    assert rating_weight(8) == 2.0
    assert rating_weight(5) == 1.0


def test_recency_boost_fresh_view_is_higher():
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    fresh = datetime(2026, 1, 9, tzinfo=timezone.utc)
    old = datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert recency_boost(fresh, now=now) > recency_boost(old, now=now)


def test_build_genre_weights():
    films = {
        "movie-1": Film(id="movie-1", title="A", genre_ids=["g1", "g2"]),
        "movie-2": Film(id="movie-2", title="B", genre_ids=["g2"]),
    }
    weights = build_genre_weights({"movie-1": 2.0, "movie-2": 1.0}, films)
    assert weights["g1"] == 2.0
    assert weights["g2"] == 3.0


def test_score_candidates_orders_by_score():
    candidates = [
        Film(id="1", title="Low", genre_ids=["g1"], imdb_rating=5.0),
        Film(id="2", title="High", genre_ids=["g1", "g2"], imdb_rating=9.0),
    ]
    results = score_candidates(candidates, {"g1": 1.0, "g2": 3.0}, reason="genre_match")
    assert results[0].film.id == "2"
    assert results[0].reason == "genre_match"


@pytest.mark.asyncio
async def test_cold_start_returns_popular():
    popular_film = Film(id="popular-1", title="Popular Film", imdb_rating=9.1)
    storage = FakeStorage()
    storage.popular = [popular_film]
    service = RecommendationService(
        repository=FakeRepository(UserSignals()),
        storage=storage,
        cache=FakeCache(),
    )

    results = await service.get_recommendations("user-1", limit=5)
    assert len(results) == 1
    assert results[0].film.id == "popular-1"
    assert results[0].reason == "popular"


@pytest.mark.asyncio
async def test_genre_based_recommendations():
    watched = Film(
        id="watched-1",
        title="Watched",
        genre_ids=["genre-action"],
        imdb_rating=8.0,
    )
    candidate = Film(
        id="candidate-1",
        title="Candidate",
        genre_ids=["genre-action"],
        imdb_rating=8.5,
    )
    storage = FakeStorage()
    storage.films = {"watched-1": watched}
    storage.recommend_result = [candidate]
    signals = UserSignals(
        interactions=[
            MovieInteraction(movie_id="watched-1", weight=3.0, source="page_view"),
        ]
    )
    service = RecommendationService(
        repository=FakeRepository(signals),
        storage=storage,
        cache=FakeCache(),
    )

    results = await service.get_recommendations("user-1", limit=5)
    assert len(results) == 1
    assert results[0].film.id == "candidate-1"
    assert results[0].reason == "genre_match"


@pytest.mark.asyncio
async def test_viewing_history_deduplicates():
    history = [
        {
            "movie_id": "movie-1",
            "duration_ms": 1000,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
    ]
    service = RecommendationService(
        repository=FakeRepository(UserSignals(), history=history),
        storage=FakeStorage(),
        cache=FakeCache(),
    )
    items = await service.get_viewing_history("user-1", limit=10)
    assert len(items) == 1
    assert items[0]["movie_id"] == "movie-1"


@pytest.mark.asyncio
async def test_recommendations_are_cached():
    popular_film = Film(id="popular-1", title="Popular Film", imdb_rating=9.1)
    storage = FakeStorage()
    storage.popular = [popular_film]
    cache = FakeCache()
    service = RecommendationService(
        repository=FakeRepository(UserSignals()),
        storage=storage,
        cache=cache,
    )

    await service.get_recommendations("user-1", limit=5)
    storage.popular = []
    results = await service.get_recommendations("user-1", limit=5)
    assert len(results) == 1
    assert results[0].film.id == "popular-1"
