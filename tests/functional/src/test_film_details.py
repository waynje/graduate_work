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
                    "title": "The Star",
                    "imdb_rating": 9.1,
                    "description": "Some description",
                    "director": ["Stan"],
                    "genre": ["Action"],
                    "actors_names": "Ann, Bob",
                    "writers_names": "Ben, Howard",
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
                    "title": "Other Film",
                    "imdb_rating": 9.1,
                    "description": "Different description",
                    "director": ["Stan"],
                    "genre": ["Action"],
                    "actors_names": "Ann, Bob",
                    "writers_names": "Ben, Howard",
                    "created_at": datetime.datetime.now().isoformat(),
                    "updated_at": datetime.datetime.now().isoformat(),
                    "film_work_type": "movie",
                },
            }
        )
    return actions


@pytest.mark.asyncio
async def test_film_details_redis_cache_and_not_found(
    es_write_data,
    es_upsert_doc,
    make_get_request,
    redis_client,
):
    film_id = str(uuid.uuid4())
    missing_id = str(uuid.uuid4())

    doc = {
        "id": film_id,
        "title": "First Title",
        "imdb_rating": 9.1,
        "description": "Some description",
        "director": ["Stan"],
        "genre": ["Action"],
        "actors_names": "Ann, Bob",
        "writers_names": "Ben, Howard",
        "created_at": datetime.datetime.now().isoformat(),
        "updated_at": datetime.datetime.now().isoformat(),
        "film_work_type": "movie",
    }

    await es_write_data(
        [
            {"_index": test_settings.es_index, "_id": film_id, "_source": doc},
        ]
    )

    assert await redis_client.get(film_id) is None

    status, body = await make_get_request(f"/{film_id}/")
    assert status == HTTPStatus.OK
    assert body["id"] == film_id
    assert body["title"] == "First Title"

    cached = await redis_client.get(film_id)
    assert cached is not None

    updated_doc = {**doc, "title": "Second Title"}
    await es_upsert_doc(film_id, updated_doc)

    status, body = await make_get_request(f"/{film_id}/")
    assert status == HTTPStatus.OK
    assert body["title"] == "First Title"

    assert await redis_client.get(missing_id) is None
    status, _ = await make_get_request(f"/{missing_id}/")
    assert status == HTTPStatus.NOT_FOUND
    assert await redis_client.get(missing_id) is None


@pytest.mark.asyncio
async def test_film_details_invalid_uuid(make_get_request):
    status, _ = await make_get_request("/not-a-uuid/")
    assert status == HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_films_list_output_all(make_get_request, es_write_data, es_data_star):
    await es_write_data(es_data_star)
    status, body = await make_get_request("/", query_params={"page[number]": 1, "page[size]": 500})
    assert status == HTTPStatus.OK
    assert isinstance(body, list)
    assert len(body) == 60
    assert body[0]["title"] == "The Star"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query_params",
    [
        {"page[number]": 0, "page[size]": 10},
        {"page[number]": -1, "page[size]": 10},
        {"page[number]": 1, "page[size]": 0},
        {"page[number]": 1, "page[size]": 501},
        {"page[number]": 1, "page[size]": -1},
        {"genre": "not-a-uuid"},
    ],
)
async def test_films_list_validation(make_get_request, query_params):
    status, body = await make_get_request("/", query_params=query_params)
    assert status == HTTPStatus.UNPROCESSABLE_ENTITY
    assert "detail" in body


@pytest.mark.asyncio
async def test_films_list_redis_cache(
    make_get_request,
    es_write_data,
    es_data_star,
    es_data_other,
    redis_client,
):
    await es_write_data(es_data_star)

    query_params = {"page[number]": 1, "page[size]": 60}
    status, body = await make_get_request("/", query_params=query_params)
    assert status == HTTPStatus.OK
    assert len(body) == 60
    assert body[0]["title"] == "The Star"

    cache_key = build_search_cache_key(
        query=None,
        genre=None,
        sort=None,
        page_number=1,
        page_size=60,
    )
    assert await redis_client.exists(cache_key) == 1

    await es_write_data(es_data_other)
    status2, body2 = await make_get_request("/", query_params=query_params)
    assert status2 == HTTPStatus.OK
    assert len(body2) == 60
    assert body2[0]["title"] == "The Star"

