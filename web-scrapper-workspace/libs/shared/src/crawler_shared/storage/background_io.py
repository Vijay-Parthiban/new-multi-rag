import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait

logger = logging.getLogger(__name__)


def flush_background_writes(
    executor: ThreadPoolExecutor,
    tasks: list[Callable[[], None]],
    *,
    label: str = "background_io",
) -> None:
    """Run disk writes in parallel and block until all complete."""
    if not tasks:
        return

    futures: list[Future[None]] = [executor.submit(task) for task in tasks]
    done, not_done = wait(futures)
    if not_done:
        logger.error("%s incomplete_writes=%d", label, len(not_done))

    for future in done:
        future.result()

    logger.info("%s_completed tasks=%d", label, len(futures))
