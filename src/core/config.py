from __future__ import annotations

import os
from functools import lru_cache
from logging import config as logging_config
from typing import Optional

from core.logger import LOGGING
from pydantic_settings import BaseSettings, SettingsConfigDict

logging_config.dictConfig(LOGGING)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_db: str
    postgres_user: str
    postgres_password: str
    postgres_host: str
    postgres_port: int

    redis_host: str = "localhost"
    redis_port: int = 6379

    elastic_schema: str = "http"
    elastic_host: str = "localhost"
    elastic_port: int = 9200

    etl_index_name: str = "movies"
    etl_schema_path: str = f"{BASE_DIR}/../es_schema.json"
    etl_state_file_path: str = f"{BASE_DIR}/../state.json"
    etl_batch_size: int = 200

    film_cache_expire_in_seconds: int = 300
    recommendations_cache_ttl_seconds: int = 300
    auth_access_token_ttl_seconds: int = 900
    auth_refresh_token_ttl_seconds: int = 864000
    auth_jwt_secret: str
    auth_jwt_algorithm: str = "HS256"
    auth_jwt_issuer: str
    auth_jwt_audience: str
    auth_roles_cache_ttl_seconds: int = 300
    auth_superuser_login: str
    auth_superuser_password: str
    auth_login_rate_limit_window_seconds: int = 60
    auth_login_rate_limit_attempts: int = 5
    api_rate_limit_window_seconds: int = 60
    api_rate_limit_requests: int = 200
    api_rate_limit_exempt_paths: str = "/api/openapi,/api/openapi.json"

    request_id_header_name: str = "X-Request-Id"
    tracing_enabled: bool = True
    tracing_service_name: str = "auth-content-service"
    jaeger_host: str = "jaeger"
    jaeger_port: int = 6831

    auth_google_client_id: Optional[str] = None
    auth_google_client_secret: Optional[str] = None
    auth_google_redirect_uri: Optional[str] = None
    auth_google_authorize_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    auth_google_token_url: str = "https://oauth2.googleapis.com/token"
    auth_google_userinfo_url: str = "https://openidconnect.googleapis.com/v1/userinfo"
    auth_google_oauth_state_ttl_seconds: int = 600
    auth_google_post_login_redirect_url: str = "http://localhost:8000/api/openapi"

    pg_pool_min_size: int = 1
    pg_pool_max_size: int = 10

    @property
    def postgres_dsn(self) -> str:
        return (
            "dbname={db} user={user} password={password} host={host} port={port}".format(
                db=self.postgres_db,
                user=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
            )
        )

    @property
    def elasticsearch_url(self) -> str:
        return f"{self.elastic_schema}://{self.elastic_host}:{self.elastic_port}"

    @property
    def api_rate_limit_exempt_paths_list(self) -> list[str]:
        return [item.strip() for item in self.api_rate_limit_exempt_paths.split(",") if item.strip()]


@lru_cache()
def get_settings() -> Settings:
    return Settings()
