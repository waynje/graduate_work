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

    async def get_by_ids(self, film_ids: list[str]) -> dict[str, Film]:
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

    async def recommend(
        self,
        *,
        genre_ids: list[str],
        exclude_ids: list[str],
        limit: int,
    ) -> list[Film]:
        ...

    async def get_popular(self, *, exclude_ids: list[str], limit: int) -> list[Film]:
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
    async def get_by_ids(self, film_ids: list[str]) -> dict[str, Film]:
        if not film_ids:
            return {}
        docs = await self.elastic.mget(index=self.index_name, ids=film_ids)
        result: dict[str, Film] = {}
        for doc in docs.get("docs", []):
            if doc.get("found"):
                film = Film(**doc["_source"])
                result[film.id] = film
        return result

    @backoff(max_retries=5)
    async def recommend(
        self,
        *,
        genre_ids: list[str],
        exclude_ids: list[str],
        limit: int,
    ) -> list[Film]:
        filters: list[dict] = []
        if genre_ids:
            filters.append({"terms": {"genre_ids": genre_ids}})
        if exclude_ids:
            filters.append({"bool": {"must_not": [{"ids": {"values": exclude_ids}}]}})

        query: dict = {"match_all": {}}
        if filters:
            query = {"bool": {"filter": filters}}

        doc = await self.elastic.search(
            index=self.index_name,
            query=query,
            sort=[{"imdb_rating": {"order": "desc", "missing": "_last"}}],
            size=limit,
        )
        hits = doc.get("hits", {}).get("hits", [])
        return [Film(**item["_source"]) for item in hits]

    @backoff(max_retries=5)
    async def get_popular(self, *, exclude_ids: list[str], limit: int) -> list[Film]:
        query: dict = {"match_all": {}}
        if exclude_ids:
            query = {"bool": {"must_not": [{"ids": {"values": exclude_ids}}]}}

        doc = await self.elastic.search(
            index=self.index_name,
            query=query,
            sort=[{"imdb_rating": {"order": "desc", "missing": "_last"}}],
            size=limit,
        )
        hits = doc.get("hits", {}).get("hits", [])
        return [Film(**item["_source"]) for item in hits]

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
