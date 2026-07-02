from __future__ import annotations

import hashlib
import json
from typing import List, Optional

from fastapi import Depends

from db.elastic import get_elastic
from db.redis import get_redis
from models.film import Film
from services.storage import (
    ElasticsearchFilmStorage,
    FilmCacheStorage,
    FilmSearchStorage,
    FilmSearchCacheStorage,
    RedisFilmCacheStorage,
    RedisFilmSearchCacheStorage,
)
from core.config import Settings, get_settings


def build_search_cache_key(
    *,
    query: Optional[str],
    genre: Optional[str],
    sort: Optional[str],
    page_number: int,
    page_size: int,
) -> str:
    payload = {
        "query": query,
        "genre": genre,
        "sort": sort,
        "page_number": page_number,
        "page_size": page_size,
    }
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"film:search:{digest}"


class FilmService:
    def __init__(
        self,
        cache_storage: FilmCacheStorage,
        search_storage: FilmSearchStorage,
        search_cache_storage: FilmSearchCacheStorage,
    ):
        self.cache_storage = cache_storage
        self.search_storage = search_storage
        self.search_cache_storage = search_cache_storage

    async def get_by_id(self, film_id: str) -> Optional[Film]:
        film = await self.cache_storage.get(film_id)
        if not film:
            film = await self.search_storage.get_by_id(film_id)
            if not film:
                return None
            await self.cache_storage.set(film)

        return film

    async def search(
        self,
        *,
        query: Optional[str] = None,
        genre: Optional[str] = None,
        sort: Optional[str] = None,
        page_number: int = 1,
        page_size: int = 50,
    ) -> List[Film]:
        cache_key = build_search_cache_key(
            query=query,
            genre=genre,
            sort=sort,
            page_number=page_number,
            page_size=page_size,
        )
        cached = await self.search_cache_storage.get(cache_key)
        if cached is not None:
            return cached

        films = await self.search_storage.search(
            query=query,
            genre=genre,
            sort=sort,
            page_number=page_number,
            page_size=page_size,
        )

        await self.search_cache_storage.set(cache_key, films)
        return films


def get_film_service(
    redis=Depends(get_redis),
    elastic=Depends(get_elastic),
    settings: Settings = Depends(get_settings),
) -> FilmService:
    cache = RedisFilmCacheStorage(redis=redis, expire_seconds=settings.film_cache_expire_in_seconds)
    storage = ElasticsearchFilmStorage(elastic=elastic, index_name=settings.etl_index_name)
    search_cache = RedisFilmSearchCacheStorage(
        redis=redis, expire_seconds=settings.film_cache_expire_in_seconds
    )
    return FilmService(
        cache_storage=cache,
        search_storage=storage,
        search_cache_storage=search_cache,
    )
