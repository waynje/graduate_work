import asyncio
import logging
import sys

from .base_storage import JsonFileStorage, State
from .config import Settings
from .es import ElasticsearchLoader
from .pg import PostgresExtractor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

STATE_KEY = "last_updated"
INITIAL_AFTER = "1970-01-01 00:00:00"


async def main() -> None:
    settings = Settings()
    state = State(JsonFileStorage(settings.etl_state_file_path))
    last = state.get_state(STATE_KEY) or INITIAL_AFTER

    loader = ElasticsearchLoader(
        settings.elasticsearch_url,
        settings.etl_index_name,
        settings.etl_schema_path,
    )

    try:
        await loader.ensure_index()
    except Exception as e:
        logger.exception("ensure_index: %s", e)
        raise

    try:
        async with await PostgresExtractor.create(settings.postgres_dsn, settings.etl_batch_size) as extractor:
            while True:
                docs, new_last = await extractor.extract_batch(last)
                if not docs:
                    logger.info("No more data")
                    break
                await loader.load_batch(docs)
                state.set_state(STATE_KEY, new_last)
                last = new_last
                if len(docs) < settings.etl_batch_size:
                    break
    finally:
        await loader.close()

    logger.info("Done")


if __name__ == "__main__":
    asyncio.run(main())
