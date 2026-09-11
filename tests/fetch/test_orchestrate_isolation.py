"""One broken site must never stall the sweep."""

import asyncio

from lge.fetch.orchestrate import gather_bounded


def test_one_failing_entity_is_omitted_and_the_rest_complete():
    async def ok(v):
        return v

    async def boom():
        raise ValueError("unknown url type: '/sitemap.xml'")

    factories = {"a": lambda: ok(1), "bad": boom, "c": lambda: ok(3)}
    result = asyncio.run(gather_bounded(factories, 2))
    # the failing key is absent -> the caller writes nothing for it, so its
    # idempotency marker is never set and the next run retries it
    assert result == {"a": 1, "c": 3}
