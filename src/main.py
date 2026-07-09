from contextlib import AsyncExitStack, asynccontextmanager

from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from redis.asyncio import Redis

from api.v1 import auth, films, recommendations, roles
from core.config import Settings
from core.rate_limit import RedisRateLimiterMiddleware
from core.request_context import RequestIdMiddleware
from core.tracing import setup_tracing
from db import elastic, redis
from db.postgres import close_pg_pool, ensure_auth_schema_ready, get_pg_connection, init_pg_pool
from services.auth import AuthService

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncExitStack() as stack:
        redis.redis = Redis(host=settings.redis_host, port=settings.redis_port)
        stack.push_async_callback(redis.redis.close)

        elastic.es = AsyncElasticsearch(hosts=[settings.elasticsearch_url])
        stack.push_async_callback(elastic.es.close)

        await init_pg_pool(settings)
        stack.push_async_callback(close_pg_pool)
        await ensure_auth_schema_ready()

        conn_gen = get_pg_connection()
        pg = await anext(conn_gen)
        stack.push_async_callback(conn_gen.aclose)

        service = AuthService(conn=pg, redis=redis.redis, settings=settings)
        await service.ensure_superuser()

        yield


app = FastAPI(
    docs_url='/api/openapi',
    openapi_url='/api/openapi.json',    
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)
setup_tracing(app, settings)
app.add_middleware(RequestIdMiddleware, header_name=settings.request_id_header_name)
app.add_middleware(
    RedisRateLimiterMiddleware,
    requests_limit=settings.api_rate_limit_requests,
    window_seconds=settings.api_rate_limit_window_seconds,
    exempt_path_prefixes=settings.api_rate_limit_exempt_paths_list,
)

app.include_router(films.router, prefix='/api/v1/films', tags=['films'])
app.include_router(recommendations.router, prefix='/api/v1/recommendations', tags=['recommendations'])
app.include_router(auth.router, prefix='/api/v1/auth', tags=['auth'])
app.include_router(roles.router, prefix='/api/v1/roles', tags=['roles'])