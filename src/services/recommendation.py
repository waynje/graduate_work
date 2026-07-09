from __future__ import annotations

from fastapi import Depends
from redis.asyncio import Redis

from core.config import Settings, get_settings
from db.elastic import get_elastic
from db.postgres import get_pg_connection
from db.redis import get_redis
from models.film import Film
from services.recommendation_service import (
    RecommendationCache,
    RecommendationRepository,
    RecommendationService,
    RecommendationStorage,
)
from services.storage import ElasticsearchFilmStorage


class ElasticsearchRecommendationStorage:
    def __init__(self, storage: ElasticsearchFilmStorage) -> None:
        self._storage = storage

    async def recommend(
        self,
        *,
        genre_ids: list[str],
        exclude_ids: list[str],
        limit: int,
    ) -> list[Film]:
        return await self._storage.recommend(
            genre_ids=genre_ids,
            exclude_ids=exclude_ids,
            limit=limit,
        )

    async def get_by_ids(self, movie_ids: list[str]) -> dict[str, Film]:
        return await self._storage.get_by_ids(movie_ids)

    async def get_popular(self, *, exclude_ids: list[str], limit: int) -> list[Film]:
        return await self._storage.get_popular(exclude_ids=exclude_ids, limit=limit)


async def get_recommendation_service(
    conn=Depends(get_pg_connection),
    elastic=Depends(get_elastic),
    redis: Redis = Depends(get_redis),
    settings: Settings = Depends(get_settings),
) -> RecommendationService:
    repository = RecommendationRepository(conn=conn)
    es_storage = ElasticsearchFilmStorage(elastic=elastic, index_name=settings.etl_index_name)
    storage: RecommendationStorage = ElasticsearchRecommendationStorage(es_storage)
    cache = RecommendationCache(redis=redis, expire_seconds=settings.recommendations_cache_ttl_seconds)
    return RecommendationService(repository=repository, storage=storage, cache=cache)
