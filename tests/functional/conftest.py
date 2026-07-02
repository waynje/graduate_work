import asyncio
import os
import uuid

import aiohttp
import psycopg
import pytest
import pytest_asyncio
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_bulk
from redis.asyncio import Redis
from tests.functional.settings import test_settings


@pytest_asyncio.fixture(name="es_client")
async def es_client():
    es_client = AsyncElasticsearch(hosts=test_settings.es_host, verify_certs=False)
    for _ in range(60):
        try:
            if await es_client.ping():
                yield es_client
                await es_client.close()
                return
        except Exception:
            pass
        import asyncio
        await asyncio.sleep(1)
    await es_client.close()
    raise RuntimeError(f'Elasticsearch недоступен по адресу {test_settings.es_host}')


@pytest_asyncio.fixture()
async def http_client_session():
    async with aiohttp.ClientSession() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def wait_for_api(http_client_session):
    for _ in range(60):
        try:
            async with http_client_session.get(test_settings.service_url + '/api/openapi.json') as resp:
                if resp.status == 200:
                    return
        except Exception:
            pass
        await asyncio.sleep(1)
    raise RuntimeError(f'FastAPI недоступен по адресу {test_settings.service_url}')


@pytest.fixture()
def make_get_request(http_client_session, film_auth_headers):
    async def inner(path: str, query_params: dict | None = None, headers: dict | None = None):
        base_url = test_settings.service_url.rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        if not path.endswith("/"):
            path += "/"
        url = f"{base_url}/api/v1/films{path}"

        request_headers = film_auth_headers if headers is None else headers
        async with http_client_session.get(url, params=query_params, headers=request_headers) as resp:
            body = await resp.json()
            return resp.status, body

    return inner


@pytest.fixture()
def make_post_api_request(http_client_session):
    async def inner(path: str, payload: dict | None = None, headers: dict | None = None):
        base_url = test_settings.service_url.rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        url = f"{base_url}{path}"
        async with http_client_session.post(url, json=payload, headers=headers) as resp:
            try:
                body = await resp.json()
            except Exception:
                body = None
            return resp.status, body

    return inner


@pytest.fixture()
def make_get_api_request(http_client_session):
    async def inner(path: str, query_params: dict | None = None, headers: dict | None = None):
        base_url = test_settings.service_url.rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        url = f"{base_url}{path}"
        async with http_client_session.get(url, params=query_params, headers=headers) as resp:
            body = await resp.json()
            return resp.status, body

    return inner


@pytest_asyncio.fixture()
async def film_auth_headers(make_post_api_request):
    login = f"film_user_{uuid.uuid4().hex[:8]}"
    password = "StrongPass123"
    await make_post_api_request("/api/v1/auth/register", payload={"login": login, "password": password})
    status, body = await make_post_api_request("/api/v1/auth/login", payload={"login": login, "password": password})
    if status != 200:
        raise RuntimeError("Cannot get test auth token for films API")
    return {"Authorization": f"Bearer {body['access_token']}"}


@pytest_asyncio.fixture()
async def redis_client():
    client = Redis(host=test_settings.redis_host, port=6379)
    for _ in range(60):
        try:
            if await client.ping():
                break
        except Exception:
            pass
        await asyncio.sleep(1)
    else:
        await client.aclose()
        raise RuntimeError(f'Redis недоступен по адресу {test_settings.redis_host}')

    yield client
    await client.aclose()


@pytest_asyncio.fixture(autouse=True)
async def redis_clean(redis_client):
    await redis_client.flushdb()

@pytest.fixture()
def es_upsert_doc(es_client):
    async def inner(doc_id: str, doc: dict):
        actions = [{"_index": test_settings.es_index, "_id": doc_id, "_source": doc}]
        _, errors = await async_bulk(client=es_client, actions=actions)
        if errors:
            raise Exception("Ошибка записи данных в Elasticsearch")
        await es_client.indices.refresh(index=test_settings.es_index)

    return inner


@pytest.fixture(name="es_write_data")
def es_write_data(es_client):
    async def inner(data: list[dict]):
        if await es_client.indices.exists(index=test_settings.es_index):
            await es_client.indices.delete(index=test_settings.es_index)
        await es_client.indices.create(index=test_settings.es_index, body=test_settings.es_index_mapping)

        updated, errors = await async_bulk(client=es_client, actions=data)
        await es_client.indices.refresh(index=test_settings.es_index)

        if errors:
            raise Exception('Ошибка записи данных в Elasticsearch')
    return inner 


@pytest_asyncio.fixture(autouse=True)
async def auth_tables_clean(wait_for_api):
    conninfo = (
        "dbname={db} user={user} password={password} host={host} port={port}".format(
            db=os.getenv("POSTGRES_DB", "movies"),
            user=os.getenv("POSTGRES_USER", "postgres"),
            password=os.getenv("POSTGRES_PASSWORD", "postgres"),
            host=os.getenv("POSTGRES_HOST", "movies-db"),
            port=os.getenv("POSTGRES_PORT", "5432"),
        )
    )
    conn = await psycopg.AsyncConnection.connect(conninfo=conninfo)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                TRUNCATE TABLE auth_login_history, auth_refresh_tokens, auth_social_accounts, auth_user_roles, auth_users
                RESTART IDENTITY CASCADE;
                """
            )
            await cur.execute(
                """
                DELETE FROM auth_roles WHERE name NOT IN ('user', 'admin');
                """
            )
        await conn.commit()
    finally:
        await conn.close()