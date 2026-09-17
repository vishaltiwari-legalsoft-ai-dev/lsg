"""The pacer: a rest once the window's worth went out, a retry after a dropped
connection, one patient second try on a bot check and then a cooldown --
the rules DuckDuckGo taught us (D-039), now the same for every engine."""

from __future__ import annotations

from lge.search.base import SearchBlocked, is_failure
from lge.search.pace import Pace, Pacer


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.now += s


def _pacer(clock: Clock, **pace) -> Pacer:
    return Pacer(Pace(**pace), monotonic=clock.monotonic, sleep=clock.sleep, jitter=lambda a, b: 0)


def test_rests_once_the_windows_worth_has_gone_out():
    clock = Clock()
    p = _pacer(clock, window_queries=2, window_s=100.0)
    ok = lambda: []  # noqa: E731
    p.call(ok, engine="x")
    p.call(ok, engine="x")
    assert clock.slept == []  # two inside the window: no rest yet
    p.call(ok, engine="x")
    assert clock.slept == [100.0]  # the third waits until the first has aged out
    p.call(ok, engine="x")
    assert clock.slept == [100.0]  # the window has room again


def test_keeps_the_steady_interval():
    clock = Clock()
    p = _pacer(clock, interval_s=8.0)
    p.call(lambda: [], engine="x")
    p.call(lambda: [], engine="x")
    assert clock.slept == [8.0]


def test_no_results_is_an_empty_answer_and_an_error_is_a_failure_row():
    clock = Clock()
    p = _pacer(clock, backoff_s=())
    assert p.call(lambda: [], engine="ddg") == []

    def broken():
        raise RuntimeError("Ratelimit")

    failed = p.call(broken, engine="ddg")
    assert is_failure(failed)
    assert failed[0]["body"].startswith("search failed: RuntimeError: Ratelimit")


def test_retries_a_dropped_connection_then_gives_up():
    clock = Clock()
    p = _pacer(clock, backoff_s=(1.0, 2.0))
    calls: list[int] = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("error sending request")
        return [{"title": "ok", "href": "https://x/", "body": ""}]

    assert p.call(flaky, engine="x")[0]["title"] == "ok"
    assert clock.slept == [1.0, 2.0]  # waited before each retry

    clock.slept.clear()

    def dead():
        raise ConnectionError("error sending request")

    assert is_failure(p.call(dead, engine="x"))
    assert clock.slept == [1.0, 2.0]  # two retries, then the failure is reported


def test_a_bot_check_gets_one_patient_retry_then_a_cooldown():
    clock = Clock()
    p = _pacer(clock, block_backoff_s=90.0, block_cooldown_s=1200.0)
    checks: list[int] = []

    def checking():
        checks.append(1)
        raise SearchBlocked("202")

    failed = p.call(checking, engine="ddg")
    assert len(checks) == 2 and clock.slept == [90.0]  # waited once, asked once more
    assert "blocked" in failed[0]["body"]
    # every later query fails at once, without asking the engine
    assert p.blocked_reason() is not None
    assert is_failure(p.call(checking, engine="ddg")) and len(checks) == 2
    clock.now += 1200.0
    assert p.blocked_reason() is None  # the cooldown is over
