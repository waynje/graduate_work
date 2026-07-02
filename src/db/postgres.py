from typing import AsyncGenerator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from core.config import Settings, get_settings

pg_pool: AsyncConnectionPool | None = None


async def init_pg_pool(settings: Settings) -> None:
    global pg_pool
    if pg_pool is not None:
        return
    pg_pool = AsyncConnectionPool(
        conninfo=settings.postgres_dsn,
        min_size=settings.pg_pool_min_size,
        max_size=settings.pg_pool_max_size,
        kwargs={"row_factory": dict_row},
        open=False,
    )
    await pg_pool.open()


async def close_pg_pool() -> None:
    global pg_pool
    if pg_pool is not None:
        await pg_pool.close()
        pg_pool = None


async def get_pg_connection() -> AsyncGenerator[psycopg.AsyncConnection, None]:
    settings = get_settings()
    if pg_pool is None:
        await init_pg_pool(settings)
    async with pg_pool.connection() as conn:
        yield conn


async def ensure_auth_schema_ready() -> None:
    if pg_pool is None:
        raise RuntimeError("Postgres pool is not initialized")
    required_tables = (
        "auth_users",
        "auth_roles",
        "auth_user_roles",
        "auth_refresh_tokens",
        "auth_login_history",
    )
    async with pg_pool.connection() as conn:
        async with conn.cursor() as cur:
            for table_name in required_tables:
                await cur.execute("SELECT to_regclass(%s);", (f"public.{table_name}",))
                row = await cur.fetchone()
                if not row or row["to_regclass"] is None:
                    raise RuntimeError(
                        "Auth schema is not initialized. Run migrations before starting the service."
                    )