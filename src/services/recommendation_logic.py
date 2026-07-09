from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from models.film import Film

MOVIE_ID_PATTERN = re.compile(
    r"/movies/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


@dataclass
class MovieInteraction:
    movie_id: str
    weight: float
    source: str


@dataclass
class UserSignals:
    interactions: list[MovieInteraction] = field(default_factory=list)

    @property
    def movie_ids(self) -> set[str]:
        return {item.movie_id for item in self.interactions}

    @property
    def movie_weights(self) -> dict[str, float]:
        weights: dict[str, float] = {}
        for item in self.interactions:
            weights[item.movie_id] = weights.get(item.movie_id, 0.0) + item.weight
        return weights


@dataclass
class RecommendationResult:
    film: Film
    score: float
    reason: str


def parse_movie_id_from_url(page_url: str | None) -> str | None:
    if not page_url:
        return None
    match = MOVIE_ID_PATTERN.search(page_url)
    if not match:
        return None
    return match.group(1)


def page_view_weight(duration_ms: int | None) -> float:
    base = 1.0
    if duration_ms is None or duration_ms <= 0:
        return base
    return base + min(duration_ms / 60_000, 2.0)


def rating_weight(score: int) -> float:
    if score >= 9:
        return 3.0
    if score >= 7:
        return 2.0
    return 1.0


def build_genre_weights(
    movie_weights: dict[str, float],
    known_films: dict[str, Film],
) -> dict[str, float]:
    genre_weights: dict[str, float] = {}
    for movie_id, weight in movie_weights.items():
        film = known_films.get(movie_id)
        if not film:
            continue
        for genre_id in film.genre_ids:
            genre_weights[genre_id] = genre_weights.get(genre_id, 0.0) + weight
    return genre_weights


def score_candidates(
    candidates: list[Film],
    genre_weights: dict[str, float],
    *,
    reason: str,
) -> list[RecommendationResult]:
    scored: list[RecommendationResult] = []
    for film in candidates:
        genre_score = sum(genre_weights.get(genre_id, 0.0) for genre_id in film.genre_ids)
        rating_boost = film.imdb_rating or 0.0
        score = genre_score + rating_boost * 0.1
        scored.append(RecommendationResult(film=film, score=round(score, 4), reason=reason))
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def recency_boost(occurred_at: datetime | None, *, now: datetime | None = None) -> float:
    if occurred_at is None:
        return 0.0
    current = now or datetime.now(timezone.utc)
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    days_ago = max((current - occurred_at).days, 0)
    return max(0.0, 1.0 - days_ago / 90)
