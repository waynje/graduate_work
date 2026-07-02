import asyncio
import logging
import time
from functools import wraps

logger = logging.getLogger(__name__)


def backoff(
    start_sleep_time: float = 0.1,
    factor: float = 2,
    border_sleep_time: float = 60,
    max_retries: int = 5,
):
    def func_wrapper(func):
        if asyncio.iscoroutinefunction(func):
            @wraps(func)
            async def async_inner(*args, **kwargs):
                sleep_time = start_sleep_time
                for attempt in range(max_retries + 1):
                    try:
                        return await func(*args, **kwargs)
                    except Exception as e:
                        if attempt >= max_retries:
                            raise
                        logger.warning(
                            "Backoff %s (attempt %s/%s): %s, sleep %.1fs",
                            func.__name__,
                            attempt + 1,
                            max_retries + 1,
                            e,
                            sleep_time,
                        )
                        await asyncio.sleep(sleep_time)
                        sleep_time = min(sleep_time * factor, border_sleep_time)

            return async_inner

        @wraps(func)
        def sync_inner(*args, **kwargs):
            sleep_time = start_sleep_time
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt >= max_retries:
                        raise
                    logger.warning(
                        "Backoff %s (attempt %s/%s): %s, sleep %.1fs",
                        func.__name__,
                        attempt + 1,
                        max_retries + 1,
                        e,
                        sleep_time,
                    )
                    time.sleep(sleep_time)
                    sleep_time = min(sleep_time * factor, border_sleep_time)

        return sync_inner

    return func_wrapper
