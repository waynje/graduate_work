from __future__ import annotations

from typing import Optional, Protocol
import json

from elasticsearch import AsyncElasticsearch, NotFoundError
from redis.asyncio import Redis

from core.decorators import backoff
from models.film import Film


class FilmCacheStorage(Protocol):
    async def get(self, film_id: str) -> Optional[Film]:
        ...

    async def set(self, film: Film) -> None:
        ...


class FilmSearchStorage(Protocol):
    async def get_by_id(self, film_id: str) -> Optional[Film]:
        ...

    async def search(
        self,
        *,
        query: Optional[str],
        genre: Optional[str],
        sort: Optional[str],
        page_number: int,
        page_size: int,
    ) -> list[Film]:
        ...


class FilmSearchCacheStorage(Protocol):
    async def get(self, cache_key: str) -> Optional[list[Film]]:
        ...

    async def set(self, cache_key: str, films: list[Film]) -> None:
        ...


class RedisFilmSearchCacheStorage:
    def __init__(self, redis: Redis, expire_seconds: int) -> None:
        self.redis = redis
        self.expire_seconds = expire_seconds

    @backoff(max_retries=5)
    async def get(self, cache_key: str) -> Optional[list[Film]]:
        data = await self.redis.get(cache_key)
        if not data:
            return None

        raw = json.loads(data)
        return [Film.model_validate(item) for item in raw]

    @backoff(max_retries=5)
    async def set(self, cache_key: str, films: list[Film]) -> None:
        payload = [f.model_dump() for f in films]
        await self.redis.set(cache_key, json.dumps(payload), ex=self.expire_seconds)


class RedisFilmCacheStorage:
    def __init__(self, redis: Redis, expire_seconds: int) -> None:
        self.redis = redis
        self.expire_seconds = expire_seconds

    @backoff(max_retries=5)
    async def get(self, film_id: str) -> Optional[Film]:
        data = await self.redis.get(film_id)
        if not data:
            return None
        return Film.model_validate_json(data)

    @backoff(max_retries=5)
    async def set(self, film: Film) -> None:
        await self.redis.set(film.id, film.model_dump_json(), ex=self.expire_seconds)


class ElasticsearchFilmStorage:
    def __init__(self, elastic: AsyncElasticsearch, index_name: str) -> None:
        self.elastic = elastic
        self.index_name = index_name

    @backoff(max_retries=5)
    async def get_by_id(self, film_id: str) -> Optional[Film]:
        try:
            doc = await self.elastic.get(index=self.index_name, id=film_id)
        except NotFoundError:
            return None
        return Film(**doc["_source"])

    @backoff(max_retries=5)
    async def search(
        self,
        *,
        query: Optional[str],
        genre: Optional[str],
        sort: Optional[str],
        page_number: int,
        page_size: int,
    ) -> list[Film]:
        body = {"query": {"match_all": {}}}

        must = []
        filter_ = []
        if query:
            must.append({"multi_match": {"query": query, "fields": ["title^3", "description"]}})
        if genre:
            filter_.append({"term": {"genre_ids": genre}})

        if must or filter_:
            body["query"] = {"bool": {}}
            if must:
                body["query"]["bool"]["must"] = must
            if filter_:
                body["query"]["bool"]["filter"] = filter_

        if sort:
            order = "desc"
            field = sort
            if sort.startswith("-"):
                field = sort[1:]
                order = "desc"
            elif sort.startswith("+"):
                field = sort[1:]
                order = "asc"
            if field == "imdb_rating":
                body["sort"] = [{field: {"order": order, "missing": "_last"}}]

        start = max(page_number - 1, 0) * page_size
        doc = await self.elastic.search(
            index=self.index_name,
            query=body["query"],
            sort=body.get("sort", []),
            from_=start,
            size=page_size,
        )
        hits = doc.get("hits", {}).get("hits", [])
        return [Film(**item["_source"]) for item in hits]
