"""Run a coroutine from synchronous code -- the CLI, a loader, a FastAPI
route that runs in the threadpool -- whether or not this thread already has
an event loop. `asyncio.run` refuses to nest; a running loop gets the
coroutine on a helper thread with a loop of its own."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any


def run_blocking[T](factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """`factory` builds the coroutine, so it is created on the loop that runs it."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(factory())).result()
