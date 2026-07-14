# Movies + UGC Platform

Монорепозиторий учебного проекта с full-stack пайплайном:

- каталог фильмов, авторизация и **рекомендации по истории просмотров** (`FastAPI`, `PostgreSQL`, `Redis`, `Elasticsearch`);
- админка (`Django`) для управления данными;
- сбор и обработка пользовательских событий (`Flask` + `Kafka` + `PostgreSQL` + `ClickHouse`);
- ETL-контуры и наблюдаемость (Prometheus-метрики, Jaeger, ELK);
- отдельный сервис уведомлений (`notification_service`) с API/worker/scheduler.

## Что внутри репозитория

| Директория | Назначение |
|---|---|
| `src/` | FastAPI: фильмы, auth, **рекомендации** |
| `etl/` | ETL PostgreSQL → Elasticsearch |
| `django_admin/` | Django Admin |
| `ugc_service/` | UGC API + Kafka consumer |
| `ugc_etl/` | ETL Kafka → ClickHouse |
| `notification_service/` | Уведомления (API + worker + scheduler) |
| `shortlink_service/` | Сокращение ссылок для email |
| `tests/` | Функциональные, UGC и recommendation-тесты |
| `alembic/` | Миграции схемы основной БД |

## Архитектура

```mermaid
flowchart LR
    CLIENT[Frontend / Client] -->|JWT| FASTAPI[FastAPI Movies API]
    FASTAPI --> PG[(PostgreSQL)]
    FASTAPI --> REDIS[(Redis)]
    FASTAPI --> ES[(Elasticsearch)]
    ETL_PG[ETL: PostgreSQL -> Elasticsearch] --> ES
    DJANGO[Django Admin] --> PG
    DJANGO --> FASTAPI

    CLIENT -->|X-User-Id| UGC_API[UGC API Flask]
    UGC_API -->|produce| KAFKA[(Kafka: ugc.events.raw)]
    KAFKA -->|consume raw| UGC_CONSUMER[UGC Consumer]
    UGC_CONSUMER -->|persist| PG
    KAFKA -->|consume page_view| UGC_ETL[UGC ETL]
    UGC_ETL -->|insert| CH[(ClickHouse)]

    FASTAPI -->|read signals| PG
    FASTAPI -->|catalog search| ES
    FASTAPI -->|cache| REDIS

    ANY[Любой сервис] -->|HTTP| NOTIFY_API[Notification API]
    NOTIFY_API --> PG
    NOTIFY_API --> KAFKA_NOTIFY[(Kafka: notifications.dispatch)]
    KAFKA_NOTIFY --> NOTIFY_WORKER[Notification Worker]
```

## Сервисы в `docker-compose`

| Сервис | Порт | Описание |
|---|---|---|
| `movies-db` | 5432 | PostgreSQL |
| `redis` | 6379 | Кэш фильмов и рекомендаций |
| `elasticsearch` | 9201 | Поисковый индекс фильмов |
| `kibana` | 5601 | ELK UI |
| `filebeat` | — | Логи контейнеров → Elasticsearch |
| `etl` | — | ETL Postgres → Elasticsearch |
| `fastapi` | 8000 | API фильмов, auth, **рекомендаций** |
| `django-admin` | 8080 | Django admin |
| `kafka-0/1/2` | 9094–9096 | Kafka KRaft cluster |
| `kafka-ui` | 8081 | Kafka UI |
| `ugc-api` | 8001 | UGC ingestion API |
| `ugc-consumer` | — | Kafka → PostgreSQL |
| `clickhouse` | 8123, 9000 | Аналитика UGC |
| `ugc-etl-clickhouse` | 9108 | ETL Kafka → ClickHouse + metrics |
| `notification-api` | 8010 | API нотификаций |
| `notification-worker` | — | Воркер отправки email |
| `notification-scheduler` | — | Автоматические уведомления |
| `shortlink-api` | 8020 | Короткие ссылки |
| `jaeger` | 16686 | Tracing UI |

## Быстрый старт

```bash
cp .env.example .env
docker compose up -d --build
docker compose ps
```

Проверка health:

```bash
curl http://localhost:8000/api/openapi.json
curl http://localhost:8001/api/v1/events/health
curl http://localhost:8010/health
curl http://localhost:8020/health
```

## Рекомендательная система

Реализован гибридный рекомендательный контур «по истории просмотров» в духе Netflix/Spotify: персональные подсказки строятся из неявных и явных сигналов пользователя, а каталог фильмов берётся из Elasticsearch.

### Как это работает

1. **Сбор сигналов** — UGC API принимает `page_view`, `click`, `custom` события и сохраняет их в PostgreSQL (`ugc_events`) через Kafka.
2. **Профиль пользователя** — FastAPI читает из PostgreSQL:
   - просмотры страниц фильмов (`page_view` с `page_url` вида `/movies/{uuid}`);
   - высокие оценки (`movie_ratings`, score ≥ 7);
   - закладки (`user_bookmarks`).
3. **Веса взаимодействий**:
   - просмотр: базовый вес + бонус за `duration_ms` + бонус за свежесть;
   - оценка 9–10: вес 3.0, 7–8: вес 2.0;
   - закладка: вес 2.5.
4. **Content-based рекомендации** — по просмотренным фильмам строится профиль жанров; Elasticsearch ранжирует кандидатов по взвешенному совпадению жанров (`function_score`) и слегка бустит `imdb_rating`, затем Python доскорит по тому же профилю.
5. **Cold start** — если истории нет, возвращаются популярные фильмы (топ по `imdb_rating`).
6. **Кэш** — результат кэшируется в Redis с ключом `recommendations:{user_id}:{limit}:{signals_version}`; `signals_version` — MAX timestamps по page_view / ratings / bookmarks, поэтому после нового просмотра, оценки или закладки выдача пересчитывается ещё до истечения TTL.

### API

Все endpoint-ы требуют JWT Bearer token (получить через `/api/v1/auth/login`).

| Метод | Endpoint | Описание |
|---|---|---|
| `GET` | `/api/v1/recommendations/` | Персональные рекомендации |
| `GET` | `/api/v1/recommendations/history/` | История просмотров |

Параметры `GET /api/v1/recommendations/`:

- `limit` — количество рекомендаций (1–100, по умолчанию 20).

Ответ:

```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "The Matrix",
    "imdb_rating": 8.7,
    "score": 4.87,
    "reason": "genre_match"
  }
]
```

Поле `reason`:

- `genre_match` — подобрано по жанрам из истории просмотров;
- `popular` — популярный фильм (cold start или дополнение списка).

### Пример end-to-end сценария

```bash
# 1) Регистрация и логин
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"login":"demo-user","password":"StrongPass123"}'

TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"login":"demo-user","password":"StrongPass123"}' | jq -r .access_token)

USER_ID=$(curl -s http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN" | jq -r .id)

# 2) Отправить событие просмотра в UGC
curl -X POST http://localhost:8001/api/v1/events/page-view \
  -H "Content-Type: application/json" \
  -H "X-User-Id: $USER_ID" \
  -d '{
    "session_id": "session-1",
    "page_url": "/movies/550e8400-e29b-41d4-a716-446655440000",
    "duration_ms": 120000
  }'

# 3) Подождать обработки Kafka consumer (несколько секунд)
sleep 5

# 4) Получить рекомендации
curl "http://localhost:8000/api/v1/recommendations/?limit=10" \
  -H "Authorization: Bearer $TOKEN"

# 5) Посмотреть историю просмотров
curl "http://localhost:8000/api/v1/recommendations/history/?limit=20" \
  -H "Authorization: Bearer $TOKEN"
```

### Ключевые файлы

- `src/services/recommendation_logic.py` — чистая логика скоринга и парсинга;
- `src/services/recommendation.py` — сервис, PostgreSQL и Redis;
- `src/services/storage.py` — Elasticsearch-запросы для рекомендаций;
- `src/api/v1/recommendations.py` — HTTP API;
- `tests/recommendations/` — unit-тесты логики.

### Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `RECOMMENDATIONS_CACHE_TTL_SECONDS` | `300` | TTL кэша рекомендаций в Redis |

## Films API

| Метод | Endpoint | Описание |
|---|---|---|
| `GET` | `/api/v1/films/` | Список фильмов (фильтр по жанру, сортировка) |
| `GET` | `/api/v1/films/search/?query=...` | Полнотекстовый поиск |
| `GET` | `/api/v1/films/{film_id}/` | Детали фильма |

## Auth API

| Метод | Endpoint | Описание |
|---|---|---|
| `POST` | `/api/v1/auth/register` | Регистрация |
| `POST` | `/api/v1/auth/login` | JWT access + refresh |
| `POST` | `/api/v1/auth/refresh` | Ротация токена |
| `POST` | `/api/v1/auth/logout` | Выход |
| `GET` | `/api/v1/auth/me` | Профиль текущего пользователя |

## Notification Service

`notification_service` — отдельный доменный сервис с тремя процессами:

- `notification-api` — приём мгновенных, массовых и админских кампаний;
- `notification-worker` — генерация и отправка персонализированных email с retry/idempotency;
- `notification-scheduler` — автоматические уведомления по правилам.

Гибридная стратегия: API готовит заявку (template, получатели, payload), worker собирает персонализацию и рендерит шаблон.

```bash
# Мгновенное уведомление
curl -X POST http://localhost:8010/api/v1/notifications/instant \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": "movie_reminder_v1",
    "user_id": "user-42",
    "payload": {"movie_id": "movie-7"}
  }'

# WebSocket live-статусы
# wscat -c "ws://localhost:8010/ws/v1/users/user-42/notifications?token=ws-secret"
```

Подробнее: встроенная админ-панель `GET /admin/notifications?token=<NOTIFY_ADMIN_API_TOKEN>`.

## UGC API: контракт событий

| Метод | Endpoint | Описание |
|---|---|---|
| `POST` | `/api/v1/events/click` | Клик по элементу |
| `POST` | `/api/v1/events/page-view` | Просмотр страницы (источник рекомендаций) |
| `POST` | `/api/v1/events/custom` | Кастомные события (`video_completed` и др.) |

Правила:

- body валидируется Pydantic-схемами;
- `user_id` берётся из trusted-header `X-User-Id`, не из body;
- API возвращает `202` после публикации в Kafka.

```bash
curl -X POST http://localhost:8001/api/v1/events/page-view \
  -H "Content-Type: application/json" \
  -H "X-User-Id: user-7" \
  -d '{
    "session_id": "session-42",
    "page_url": "/movies/123",
    "duration_ms": 5120,
    "referrer": "/main"
  }'
```

### UGC CRUD (рейтинги, рецензии, закладки)

| Метод | Endpoint |
|---|---|
| `POST/DELETE` | `/api/v1/ugc/movies/{movie_id}/rating` |
| `GET` | `/api/v1/ugc/movies/{movie_id}/rating/stats` |
| `POST/DELETE` | `/api/v1/ugc/movies/{movie_id}/bookmarks` |
| `GET` | `/api/v1/ugc/users/{user_id}/bookmarks` |
| `POST` | `/api/v1/ugc/movies/{movie_id}/reviews` |
| `GET` | `/api/v1/ugc/movies/{movie_id}/reviews` |

## Исследование хранилища UGC (Sprint 2)

Для лайков, рецензий и закладок выбран `ugc_service` + PostgreSQL.

Таблицы:

- `movie_ratings` — оценка 0..10, уникальность `(user_id, movie_id)`;
- `movie_reviews` — текстовые рецензии;
- `review_votes` — лайк/дизлайк рецензии;
- `user_bookmarks` — закладки;
- `ugc_events` — raw-события (просмотры, клики).

Скрипты исследования в `ugc_service/research/`:

```bash
UGC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/movies' \
python3 -m ugc_service.research.generate_ugc_data --users 5000 --movies 2000 --truncate

UGC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/movies' \
python3 -m ugc_service.research.benchmark_ugc_storage --iterations 400
```

Результаты: read latency существенно ниже целевых 200 ms. ClickHouse top-10 по просмотрам — ~23 ms на 2M строк.

## Надёжность пайплайна UGC

**Kafka → PostgreSQL (`ugc-consumer`):**

- manual commit offset после успешной записи;
- невалидные payload → `ugc_rejected_events`.

**Kafka → ClickHouse (`ugc-etl-clickhouse`):**

- manual commit после вставки батча;
- `ReplacingMergeTree` + партиционирование по месяцу.

Проверка данных:

```bash
docker compose exec clickhouse clickhouse-client --query \
  "SELECT event_id, session_id, page_url, duration_ms, occurred_at FROM ugc.page_views ORDER BY occurred_at DESC LIMIT 5"
```

## Метрики и наблюдаемость

- UGC ETL metrics: `http://localhost:9108/metrics`
- Jaeger UI: `http://localhost:16686`
- Kibana: `http://localhost:5601` (data view: `movies-platform-logs-*`)
- Sentry для `ugc-api` через `SENTRY_DSN`

## Управление схемой БД

Схема управляется Alembic-миграциями. FastAPI и UGC запускают `alembic upgrade head` при старте контейнера.

```bash
alembic upgrade head
```

## Тесты

```bash
# Unit-тесты рекомендаций
PYTHONPATH=src pytest tests/recommendations -q

# UGC-тесты
pytest tests/ugc -q

# Функциональные тесты (требуют docker-compose.test.yml)
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit tests
```

## Остановка и очистка

```bash
docker compose down
docker compose down -v
```

Проект: https://github.com/waynje/graduate_work
