"""What the paid search provider says it charged. Serper returns a `credits`
field in every answer; the engines add it here as it comes in, and a
component prints the run's total in its notes, so the number the engine
reports and the number on the vendor's dashboard can be compared after
every run -- the check the first live run was read by (D-064).

Counted per thread: the screen's research jobs run one thread per firm,
and a job's "provider charged" line must be that job's own calls, not the
sum of everything the process did meanwhile. `reset()` for tests.
"""

from __future__ import annotations

import threading

_local = threading.local()


def _counts() -> tuple[dict[str, int], dict[str, int]]:
    if not hasattr(_local, "credits"):
        _local.credits = {}
        _local.calls = {}
    return _local.credits, _local.calls


def record(provider: str, credits: object) -> None:
    """One answered call. `credits` is whatever the provider put in the
    response; anything that is not a whole number counts as one call and
    zero known credits."""
    try:
        n = int(credits)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = 0
    cr, ca = _counts()
    cr[provider] = cr.get(provider, 0) + max(0, n)
    ca[provider] = ca.get(provider, 0) + 1


def snapshot() -> dict[str, tuple[int, int]]:
    """{provider: (calls, credits)} so far on this thread."""
    cr, ca = _counts()
    return {p: (ca.get(p, 0), cr.get(p, 0)) for p in set(ca) | set(cr)}


def since(before: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int]]:
    """What went out between `before` (an earlier snapshot) and now."""
    now = snapshot()
    out: dict[str, tuple[int, int]] = {}
    for p, (calls, credits) in now.items():
        b_calls, b_credits = before.get(p, (0, 0))
        if calls - b_calls or credits - b_credits:
            out[p] = (calls - b_calls, credits - b_credits)
    return out


def note(before: dict[str, tuple[int, int]]) -> str | None:
    """One line for a component's notes: "serper: 11 call(s), 11 credit(s)"."""
    spent = since(before)
    if not spent:
        return None
    return "; ".join(f"{p}: {c} call(s), {n} credit(s)" for p, (c, n) in sorted(spent.items()))


def reset() -> None:
    cr, ca = _counts()
    cr.clear()
    ca.clear()
