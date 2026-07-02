import datetime
from http import HTTPStatus
import uuid

import pytest

from tests.functional.settings import test_settings

from services.film import build_search_cache_key


@pytest.fixture
def es_data_star() -> list[dict]:
    actions: list[dict] = []
    for _ in range(60):
        film_id = str(uuid.uuid4())
        actions.append(
            {
                "_index": test_settings.es_index,
                "_id": film_id,
                "_source": {
                    "id": film_id,
                    "imdb_rating": 8.5,
                    "genre": ["Action", "Sci-Fi"],
                    "title": "The Star",
                    "description": "New World",
                    "director": ["Stan"],
                    "actors_names": "Ann, Bob",
                    "writers_names": "Ben, Howard",
                    "actors": [
                        {"id": "ef86b8ff-3c82-4d31-ad8e-72b69f4e3f95", "name": "Ann"},
                        {"id": "fb111f22-121e-44a7-b78f-b19191810fbf", "name": "Bob"},
                    ],
                    "writers": [
                        {"id": "caf76c67-c0fe-477e-8766-3ab3ff2574b5", "name": "Ben"},
                        {"id": "b45bd7bc-2e16-46d5-b125-983d356768c6", "name": "Howard"},
                    ],
                    "created_at": datetime.datetime.now().isoformat(),
                    "updated_at": datetime.datetime.now().isoformat(),
                    "film_work_type": "movie",
                },
            }
        )
    return actions


@pytest.fixture
def es_data_other() -> list[dict]:
    actions: list[dict] = []
    for _ in range(60):
        film_id = str(uuid.uuid4())
        actions.append(
            {
                "_index": test_settings.es_index,
                "_id": film_id,
                "_source": {
                    "id": film_id,
                    "imdb_rating": 8.5,
                    "genre": ["Action", "Sci-Fi"],
                    "title": "Other Film",
                    "description": "Completely Different",
                    "director": ["Stan"],
                    "actors_names": "Ann, Bob",
                    "writers_names": "Ben, Howard",
                    "actors": [
                        {"id": "ef86b8ff-3c82-4d31-ad8e-72b69f4e3f95", "name": "Ann"},
                        {"id": "fb111f22-121e-44a7-b78f-b19191810fbf", "name": "Bob"},
                    ],
                    "writers": [
                        {"id": "caf76c67-c0fe-477e-8766-3ab3ff2574b5", "name": "Ben"},
                        {"id": "b45bd7bc-2e16-46d5-b125-983d356768c6", "name": "Howard"},
                    ],
                    "created_at": datetime.datetime.now().isoformat(),
                    "updated_at": datetime.datetime.now().isoformat(),
                    "film_work_type": "movie",
                },
            }
        )
    return actions


@pytest.mark.parametrize(
    "query_data, expected_answer",
    [
        ({"query": "The Star"}, {"status": 200, "length": 50}),
        ({"query": "Mashed potato"}, {"status": 200, "length": 0}),
    ],
)
@pytest.mark.asyncio
async def test_search(make_get_request, es_write_data, es_data_star, query_data, expected_answer):
    await es_write_data(es_data_star)
    status, body = await make_get_request("/search", query_params=query_data)

    assert status == expected_answer["status"]
    assert isinstance(body, list)
    assert len(body) == expected_answer["length"]


@pytest.mark.asyncio
async def test_films_requires_access_token(make_get_api_request):
    status, body = await make_get_api_request("/api/v1/films/")
    assert status in (HTTPStatus.FORBIDDEN, HTTPStatus.UNAUTHORIZED)
    assert "detail" in body


@pytest.mark.asyncio
async def test_search_requires_query(make_get_request):
    status, body = await make_get_request("/search", query_params=None)
    assert status == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "detail" in body


@pytest.mark.asyncio
async def test_search_empty_query_validation(make_get_request):
    status, body = await make_get_request("/search", query_params={"query": ""})
    assert status == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "detail" in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query_params",
    [
        {"query": "The Star", "page[number]": 0},
        {"query": "The Star", "page[number]": -1},
        {"query": "The Star", "page[size]": 0},
        {"query": "The Star", "page[size]": -1},
        {"query": "The Star", "page[size]": 501},
    ],
)
async def test_search_pagination_validation(
    make_get_request,
    query_params,
):
    status, body = await make_get_request(
        "/search",
        query_params=query_params,
    )
    assert status == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "detail" in body


@pytest.mark.asyncio
async def test_search_pagination(make_get_request, es_write_data, es_data_star):
    await es_write_data(es_data_star)
    status, body = await make_get_request(
        "/search",
        query_params={"query": "The Star", "page[number]": 2, "page[size]": 10},
    )
    assert status == HTTPStatus.OK
    assert isinstance(body, list)
    assert len(body) == 10


@pytest.mark.asyncio
async def test_search_redis_cache(
    make_get_request,
    es_write_data,
    es_data_star,
    es_data_other,
    redis_client,
):
    await es_write_data(es_data_star)

    query_params = {"query": "The Star", "page[number]": 1, "page[size]": 60}
    status, body = await make_get_request("/search", query_params=query_params)
    assert status == HTTPStatus.OK
    assert isinstance(body, list)
    assert len(body) == 60
    assert body[0]["title"] == "The Star"

    cache_key = build_search_cache_key(
        query="The Star",
        genre=None,
        sort=None,
        page_number=1,
        page_size=60,
    )
    assert await redis_client.exists(cache_key) == 1

    await es_write_data(es_data_other)

    status2, body2 = await make_get_request("/search", query_params=query_params)
    assert status2 == HTTPStatus.OK
    assert isinstance(body2, list)
    assert len(body2) == 60
    assert body2[0]["title"] == "The Star"

