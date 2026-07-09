from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    configured_url = config.get_main_option("sqlalchemy.url")
    default_local = "postgresql+psycopg://postgres:postgres@localhost:5432/movies"
    if configured_url and configured_url != default_local:
        return configured_url

    notify_database_url = os.getenv("NOTIFY_DATABASE_URL")
    if notify_database_url:
        return notify_database_url

    ugc_database_url = os.getenv("UGC_DATABASE_URL")
    if ugc_database_url:
        return ugc_database_url

    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    dbname = os.getenv("POSTGRES_DB", "movies")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"


target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.begin() as connection:
        connection.exec_driver_sql("SELECT pg_advisory_lock(48712026491583591)")
        try:
            context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.exec_driver_sql("SELECT pg_advisory_unlock(48712026491583591)")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
