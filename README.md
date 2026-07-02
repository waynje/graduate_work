# Movies + UGC Platform

Монорепозиторий учебного проекта с full-stack пайплайном:

- каталог фильмов и авторизация (`FastAPI`, `PostgreSQL`, `Redis`, `Elasticsearch`);
- админка (`Django`) для управления данными;
- сбор и обработка пользовательских событий (`Flask` + `Kafka` + `PostgreSQL` + `ClickHouse`);
- ETL-контуры и наблюдаемость (Prometheus-метрики, Jaeger).
- отдельный сервис уведомлений (`notification_service`) с API/worker/scheduler.

## Что внутри репозитория

- `src/` — основной API сервиса фильмов (FastAPI).
- `etl/` — ETL из PostgreSQL в Elasticsearch.
- `django_admin/` — Django Admin для операционной работы с данными.
- `ugc_service/` — UGC API + Kafka consumer в raw-PostgreSQL.
- `ugc_etl/` — ETL из Kafka в ClickHouse (аналитическая витрина).
- `notification_service/` — сервис нотификаций (API + worker + scheduler + websocket).
- `shortlink_service/` — отдельный сервис сокращения ссылок для email.
- `tests/` — функциональные и UGC-тесты.
- `alembic/` — миграции схемы основной БД.

## Архитектура

```mermaid
flowchart LR
    CLIENT[Frontend / Client] -->|HTTP| FASTAPI[FastAPI Movies API]
    FASTAPI --> PG[(PostgreSQL)]
    FASTAPI --> REDIS[(Redis)]
    ETL_PG[ETL: PostgreSQL -> Elasticsearch] --> ES[(Elasticsearch)]
    DJANGO[Django Admin] --> PG
    DJANGO --> FASTAPI

    CLIENT -->|HTTP JSON| UGC_API[UGC API Flask]
    UGC_API -->|produce| KAFKA[(Kafka: ugc.events.raw)]
    KAFKA -->|consume raw| UGC_CONSUMER[UGC Consumer]
    UGC_CONSUMER -->|persist| PG
    KAFKA -->|consume page_view| UGC_ETL[UGC ETL]
    UGC_ETL -->|insert| CH[(ClickHouse)]

    ANY[Любой сервис платформы] -->|HTTP| NOTIFY_API[Notification API]
    ADMIN[Админ-панель/менеджер] -->|HTTP| NOTIFY_API
    NOTIFY_SCHED[Notification Scheduler] -->|создает задачи| NOTIFY_API
    NOTIFY_API -->|persist| PG
    NOTIFY_API -->|enqueue| KAFKA_NOTIFY[(Kafka: notifications.dispatch)]
    KAFKA_NOTIFY -->|consume| NOTIFY_WORKER[Notification Worker]
    NOTIFY_WORKER -->|delivery log + retries| PG
```

## Сервисы в `docker-compose`

- `movies-db` — PostgreSQL (`localhost:5432`)
- `redis` — Redis (`localhost:6379`)
- `elasticsearch` — Elasticsearch (`localhost:9200`)
- `kibana` — ELK UI (`http://localhost:5601`)
- `filebeat` — shipper логов Docker-контейнеров -> Elasticsearch
- `etl` — ETL Postgres -> Elasticsearch
- `fastapi` — API фильмов (`http://localhost:8000`)
- `django-admin` — Django admin (`http://localhost:8080/admin`)
- `kafka-0`, `kafka-1`, `kafka-2` — Kafka KRaft cluster
- `kafka-ui` — Kafka UI (`http://localhost:8081`)
- `ugc-api` — UGC ingestion API (`http://localhost:8001`)
- `ugc-consumer` — raw storage consumer (Kafka -> PostgreSQL)
- `clickhouse` — ClickHouse (`localhost:8123`, `localhost:9000`)
- `ugc-etl-clickhouse` — ETL Kafka -> ClickHouse + metrics (`http://localhost:9108/metrics`)
- `notification-api` — API нотификаций (`http://localhost:8010`)
- `notification-worker` — воркер отправки email (из Kafka/DB очереди)
- `notification-scheduler` — генератор автоматических уведомлений
- `shortlink-api` — сервис коротких ссылок (`http://localhost:8020`)
- `jaeger` — tracing UI (`http://localhost:16686`)

## Быстрый старт

```bash
docker compose up -d --build
docker compose ps
```

Проверка health:

```bash
curl http://localhost:8001/api/v1/events/health
curl http://localhost:8010/health
curl http://localhost:8020/health
```

## Notification Service (Sprint 3)

`notification_service` реализован как отдельный доменный сервис с тремя процессами:

- `notification-api` - прием мгновенных, массовых и админских кампаний;
- `notification-worker` - генерация и отправка персонализированных email c retry/idempotency и учетом preferences;
- `notification-scheduler` - генерация автоматических уведомлений по правилам без дублей после простоя.
- `websocket`-модуль в API - live-стрим статусов доставок пользователю.
- встроенная простая админ-панель: `GET /admin/notifications?token=<NOTIFY_ADMIN_API_TOKEN>`.

### Гибридный формат (API + worker + scheduler + admin)

Используется гибридная стратегия: часть данных подготавливается в API (template_id, получатели, payload, dedup_key), а часть собирается в worker (preferences пользователя, персонализация контекста, рендер шаблона, итоговый контент и статус доставки).

1. **Мгновенное уведомление от любого компонента сайта**
   - сервис вызывает `POST /api/v1/notifications/instant`;
   - API валидирует запрос, пишет `notification_requests`, публикует `request_id` в Kafka;
   - worker забирает задачу, рендерит шаблон и пишет результат в `notification_deliveries`;
   - если Kafka временно недоступна, задача остается в БД и worker подберет ее через DB polling.

2. **Автоматические уведомления на большую группу**
   - в админке заводится правило `POST /api/v1/admin/auto-rules`;
   - scheduler периодически выбирает `automatic_notification_rules.next_run_at <= now`, создает idempotent request (`dedup_key=rule:<id>:<slot>`) и сдвигает `next_run_at`;
   - при рестарте scheduler не дублирует старые/новые события за счет `dedup_key` + атомарного обновления `next_run_at`.

3. **Ручная рассылка из админ-панели**
   - менеджер создает кампанию `POST /api/v1/admin/campaigns` с `scheduled_for` или immediate;
   - API сохраняет `notification_campaigns` + соответствующий `notification_requests`;
   - worker отправляет по шаблону из единого реестра `notification_templates`.

### Как выполняются требования

- **Расширяемость каналов:** в шаблонах и доставке есть поле `channel`; сейчас используется `email`, но модель готова для `sms/push`.
- **Latency мгновенных:** worker читает Kafka + DB queue, задержка ограничена интервалом polling (секунды) и обычно остается в пределах минут.
- **Ничего не теряется:** запрос сначала фиксируется в PostgreSQL, затем отправляется в Kafka; даже при сбое Kafka задача сохраняется.
- **Без дублей после downtime:** dedup по `notification_requests.dedup_key` и уникальные ограничения доставок.
- **Пользовательские настройки:** `PUT /api/v1/users/{user_id}/preferences/email` отключает/включает email.
- **Единая шаблонизация:** все сценарии используют `notification_templates` и общий рендерер.
- **WebSocket поддержка:** `ws://localhost:8010/ws/v1/users/{user_id}/notifications` отдает live-снимки статусов доставок.
- **WebSocket авторизация:** подключение требует `?token=<NOTIFY_WEBSOCKET_API_TOKEN>`.
- **Персонализация в воркере:** воркер получает профиль по `user_id` через `NOTIFY_AUTH_USERINFO_URL_TEMPLATE`, затем рендерит письмо.
- **Сокращение ссылок:** ссылки (`*_url`) в payload автоматически сокращаются через `shortlink-api`.
- **Масштабируемость:** API/worker/scheduler горизонтально масштабируются независимо, очередь - Kafka.

### Чек-лист реализации

- Админ-панель для менеджеров: `GET /admin/notifications` (защищена manager token).
- CRUD шаблонов: `POST/GET/DELETE /api/v1/admin/templates`.
- Мгновенные, отложенные и повторяющиеся сообщения: `instant`, `campaign(scheduled_for)`, `auto-rules`.
- Фиксированные события от внешних сервисов: `POST /api/v1/events/fixed`.
- Свободный формат события (опционально): `POST /api/v1/events/free-form`.
- Выдача уведомлений пользователю (опционально): `GET /api/v1/users/{user_id}/notifications`.
- API только принимает заявки и кладет их в Kafka; рассылкой занимается `notification-worker`.
- Воркер получает профиль пользователя по `user_id` через auth endpoint и формирует персонализированный текст.
- WebSocket-сервер с авторизацией токеном: `WS /ws/v1/users/{user_id}/notifications?token=...`.
- Отдельный сервис сокращения ссылок: `shortlink-api`.

### API quick examples

```bash
# 1) Добавить шаблон
curl -X POST http://localhost:8010/api/v1/admin/templates \
  -H "Content-Type: application/json" \
  -d '{
    "id": "movie_reminder_v1",
    "channel": "email",
    "subject_template": "Не забудьте про фильм ${movie_id}",
    "body_template": "Привет, ${user_id}! Фильм ${movie_id} уже ждет вас.",
    "is_active": true
  }'

# 2) Мгновенное уведомление
curl -X POST http://localhost:8010/api/v1/notifications/instant \
  -H "Content-Type: application/json" \
  -d '{
    "template_id": "movie_reminder_v1",
    "user_id": "user-42",
    "payload": {"movie_id": "movie-7"}
  }'

# 3) История доставок по HTTP
curl http://localhost:8010/api/v1/users/user-42/notifications

# 4) Live-обновления через websocket
# wscat -c "ws://localhost:8010/ws/v1/users/user-42/notifications?token=ws-secret"

# 5) Fixed event от внешнего сервиса
curl -X POST http://localhost:8010/api/v1/events/fixed \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "user_registered",
    "user_id": "user-42",
    "payload": {"movie_url": "https://movies.local/m/7"}
  }'

# 6) Сократить ссылку напрямую
curl -X POST http://localhost:8020/api/v1/short-links \
  -H "Content-Type: application/json" \
  -d '{"target_url":"https://movies.local/movies/123?utm_source=newsletter"}'
```

## UGC API: контракт событий

Поддерживаемые endpoint:

- `POST /api/v1/events/click`
- `POST /api/v1/events/page-view`
- `POST /api/v1/events/custom`

Ключевые правила:

- body валидируется через Pydantic-схемы;
- невалидный body/JSON возвращает `422`;
- пользователь берется из trusted-header (`X-User-Id`), а не из body;
- API возвращает `202`, когда событие подтвержденно отправлено в Kafka.

Пример `click`:

```bash
curl -X POST http://localhost:8001/api/v1/events/click \
  -H "Content-Type: application/json" \
  -H "X-User-Id: user-7" \
  -d '{
    "session_id": "session-42",
    "page_url": "/movies/123",
    "element": "play_button",
    "metadata": {"source": "carousel"}
  }'
```

Пример `page_view`:

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

## Исследование хранилища UGC (Sprint 2)

### Что выбрали

Для лайков, рецензий и закладок выбран существующий `ugc_service` + текущее хранилище `PostgreSQL`.

Почему:

- критичен read latency (целевой SLA `<= 200 ms`), а для агрегаций и выборок по индексам PostgreSQL стабилен;
- не появляется новый сервис/инфраструктура: меньше операционной сложности;
- можно переиспользовать текущий контур (`docker-compose`, мониторинг, метрики ETL/consumer);
- реляционная модель хорошо подходит под связи `user -> movie`, `review -> votes`, `bookmark`.

### Как хранятся данные

Добавлены таблицы:

- `movie_ratings` — оценка пользователя фильму (`smallint` 0..10), уникальность `(user_id, movie_id)`;
- `movie_reviews` — рецензия с текстом, автором, датой и опциональной оценкой фильма;
- `review_votes` — лайк/дизлайк рецензии (`-1/1`), уникальность `(user_id, review_id)`;
- `user_bookmarks` — закладки пользователя по фильмам.

Реализованы API-сценарии:

- лайки/оценки фильма: добавить, изменить, удалить, получить агрегаты (likes/dislikes/avg);
- рецензии: добавить, проголосовать за рецензию, получить список с сортировкой (`helpful`, `created`, `score`);
- закладки: добавить, удалить, получить список пользователя.

### Скрипты исследования

Скрипты находятся в `ugc_service/research/`:

- `generate_ugc_data.py` — генерация синтетических данных;
- `benchmark_ugc_storage.py` — замер read latency и real-time кейса.

Запуск (пример):

```bash
# 1) Генерация данных
UGC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/movies' \
python3 -m ugc_service.research.generate_ugc_data \
  --users 5000 \
  --movies 2000 \
  --ratings 100000 \
  --reviews 20000 \
  --review-votes 100000 \
  --bookmarks-per-user 8 \
  --truncate

# 2) Бенчмарк
UGC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/movies' \
python3 -m ugc_service.research.benchmark_ugc_storage \
  --iterations 400 \
  --output ugc_service/research/benchmark_results.md
```

### Результаты по скорости

Актуальные результаты сохранены в `ugc_service/research/benchmark_results.md`.
Последний замер ниже выполнен локально на `sqlite+pysqlite:///./ugc_benchmark.db` (fallback-профиль без Docker).

Последний замер (400 итераций):

- Read: user likes list — avg `0.35 ms`, p95 `0.38 ms`, max `1.93 ms`
- Read: likes/dislikes count by movie — avg `0.49 ms`, p95 `0.51 ms`, max `2.21 ms`
- Read: user bookmarks list — avg `0.29 ms`, p95 `0.30 ms`, max `0.84 ms`
- Read: movie average rating — avg `0.33 ms`, p95 `0.42 ms`, max `1.02 ms`
- Realtime: rating update -> visible in aggregate — avg `0.91 ms`, p95 `0.96 ms`, max `2.18 ms`

Во всех измеренных сценариях latency существенно ниже целевых `200 ms`.

### ClickHouse speed test (Docker)

Отдельно выполнен замер на Docker-контейнере ClickHouse (`clickhouse-client --time`) для аналитического контура:

- подготовлена таблица `ugc.page_views_bench` (`MergeTree`);
- вставка `2_000_000` строк: `0.692 s` (примерно `2.89M rows/s`);
- чтение `count()` по пользователю: `0.023 s`;
- чтение top-10 фильмов по просмотрам (`GROUP BY + ORDER BY + LIMIT`): `0.023 s`;
- чтение `avg(duration_ms)` по фильму: `0.013 s`;
- real-time вставка 1 строки: `0.010 s`;
- immediate read после вставки: `0.019 s`.

Все измерения также ниже целевого ограничения `200 ms` на операции чтения.

### Решение по реализации

Выбран путь **добавления функциональности в существующий `ugc_service`**, а не отдельного сервиса.

Плюсы:

- быстрее внедрение;
- единый стек хранения для UGC-домена;
- проще поддержка (один деплой и одна кодовая база API для UGC).

Потенциальные риски:

- разрастание сервиса и усложнение ответственности;
- конкуренция OLTP-нагрузки UGC-CRUD и raw event ingestion;
- в будущем может потребоваться вынос heavy-read в отдельные read-модели/кэш.

Когда имеет смысл выделять отдельный сервис:

- если UGC-домен вырастает в отдельную продуктовую команду;
- если нагрузка по рецензиям/рейтингам начинает мешать ingestion-пайплайну;
- если потребуется самостоятельное масштабирование и отдельный SLA.

## Надежность пайплайна UGC


### Kafka -> PostgreSQL (`ugc-consumer`)

- `enable_auto_commit=False`;
- offset коммитится только после успешной обработки события;
- при ошибке записи offset не коммитится, consumer делает `seek` на проблемный offset;
- невалидные payload пишутся в таблицу `ugc_rejected_events` с причиной.

### Kafka -> ClickHouse (`ugc-etl-clickhouse`)

- `enable_auto_commit=False`;
- offset коммитится только после успешной вставки батча;
- невалидные события пропускаются с reason-категорией (`ugc_etl_events_rejected_total{reason=...}`);
- DDL использует `PARTITION BY toYYYYMM(occurred_at)` + `ReplacingMergeTree`.

## Метрики и наблюдаемость

UGC ETL публикует метрики на `http://localhost:9108/metrics`, включая:

- чтение/запись/skip событий;
- причины reject по типам валидации;
- ошибки Kafka и ClickHouse;
- размер батча и длительность вставки;
- оценка consumer lag;
- memory RSS/VMS процесса ETL.

Проверка:

```bash
curl http://localhost:9108/metrics
```

Логи всех контейнеров собираются через `filebeat` в `elasticsearch` и доступны в `kibana`.

Открыть Kibana:

```bash
open http://localhost:5601
```

Рекомендуемый data view в Discover:

- `movies-platform-logs-*`

Sentry включается только для Flask-сервиса `ugc-api` через переменные окружения:

- `SENTRY_DSN` — DSN проекта в Sentry;
- `SENTRY_ENVIRONMENT` — окружение (`development`, `staging`, `production`);
- `SENTRY_TRACES_SAMPLE_RATE` — sampling для трассировок, например `0.0` или `0.1`.

Без `SENTRY_DSN` приложение работает как обычно (Sentry отключен).

## Проверка данных в ClickHouse

```bash
docker compose exec clickhouse clickhouse-client --query \
  "SELECT event_id, session_id, page_url, duration_ms, occurred_at FROM ugc.page_views ORDER BY occurred_at DESC LIMIT 5"
```

## Управление схемой БД

Схема UGC теперь управляется через Alembic-миграции.

- для локального bootstrap можно включить `UGC_RUN_MIGRATIONS_ON_STARTUP=true`;
- для production рекомендуется отдельный шаг `alembic upgrade head` в pipeline/deploy;
- `create_tables()` оставлен только как тестовый helper для in-memory/sqlite сценариев.

Для `notification_service` используется тот же подход: контейнеры могут запускать миграции через `NOTIFY_RUN_MIGRATIONS_ON_STARTUP=true`, а в production лучше выносить `alembic upgrade head` в отдельный deploy-step.

## Пагинация UGC-списков

Сейчас endpoint-ы используют `limit/offset`, что удобно для простых выборок.
Для больших пользовательских списков (лайки/закладки) следующий шаг - перейти на cursor-based пагинацию по паре (`created_at`, `id`) для стабильной производительности на больших offset.

## Совместимость gevent

`ugc_service/wsgi.py` использует `gevent.monkey.patch_all()`. Перед обновлением клиентов Kafka/PostgreSQL фиксируйте совместимые версии и проверяйте end-to-end сценарии (publish/consume/read) в staging, чтобы избежать регрессий из-за monkey patching.

## Тесты

UGC-тесты:

```bash
pytest tests/ugc -q
```

Функциональные тесты:

```bash
pytest tests/functional -q
```

## Остановка и очистка

```bash
docker compose down
docker compose down -v
```

Проект: https://github.com/waynje/ugc_sprint_1