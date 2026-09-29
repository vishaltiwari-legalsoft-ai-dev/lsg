"""OpenRouter chat-completions client — the user holds an OpenRouter key,
not an Anthropic key, so P8/P9 call Claude through OpenRouter's
OpenAI-compatible Chat Completions API rather than the Anthropic SDK.

Never logs the API key. Retries 429/5xx with exponential backoff plus
jitter, honouring `Retry-After` when the server sends one, up to
`max_retries` attempts total.

Every failure leaves here as an `LLMCallError` — including a 200 whose body
carries an `error` object rather than `choices`, which OpenRouter does send
(free-tier throttling, upstream provider faults). `lge/llm/run.py` catches
only `LLMCallError`, so anything else escaping this module takes down a
whole run instead of one firm.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Any

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_RETRYABLE_STATUSES = {429}


class LLMCallError(Exception):
    """Raised when an OpenRouter call does not succeed within the retry
    budget (HTTP-level failure, timeout, or a non-2xx status)."""


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str
    usage: dict[str, Any] | None
    raw: dict[str, Any]


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


async def _sleep_backoff(attempt: int, base: float, cap: float, retry_after: float | None) -> None:
    if retry_after is not None:
        delay = retry_after
    else:
        delay = min(cap, base * (2 ** (attempt - 1)))
        delay = delay * (0.5 + random.random())  # +/- jitter around the backoff
    await asyncio.sleep(delay)


async def call_openrouter(
    http_client: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    system: str,
    user: str,
    response_format: dict[str, Any],
    max_tokens: int,
    timeout_s: float,
    referer: str,
    title: str,
    max_retries: int = 3,
    backoff_base_s: float = 1.0,
    backoff_max_s: float = 30.0,
) -> LLMResponse:
    """POST one chat-completions request, retrying transient failures.
    `max_retries` is the total number of attempts allowed (>=1)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": referer,
        "X-Title": title,
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": response_format,
        "max_tokens": max_tokens,
    }

    attempt = 0
    while True:
        attempt += 1
        try:
            resp = await http_client.post(
                OPENROUTER_URL, headers=headers, json=body, timeout=timeout_s
            )
        except httpx.TimeoutException as exc:
            if attempt >= max_retries:
                raise LLMCallError(f"timeout after {attempt} attempt(s)") from exc
            await _sleep_backoff(attempt, backoff_base_s, backoff_max_s, None)
            continue
        except httpx.HTTPError as exc:
            if attempt >= max_retries:
                raise LLMCallError(f"transport error after {attempt} attempt(s): {exc}") from exc
            await _sleep_backoff(attempt, backoff_base_s, backoff_max_s, None)
            continue

        if resp.status_code in _RETRYABLE_STATUSES or resp.status_code >= 500:
            if attempt >= max_retries:
                raise LLMCallError(
                    f"HTTP {resp.status_code} after {attempt} attempt(s): {resp.text[:500]}"
                )
            retry_after = _parse_retry_after(resp.headers.get("retry-after"))
            await _sleep_backoff(attempt, backoff_base_s, backoff_max_s, retry_after)
            continue

        if resp.status_code >= 400:
            raise LLMCallError(f"HTTP {resp.status_code}: {resp.text[:500]}")

        payload = resp.json()
        break

    # OpenRouter answers 200 with a bare {"error": {...}} body for some
    # upstream-provider failures and for free-tier throttling -- there is no
    # `choices` key at all. Indexing it blind raised KeyError, which is not
    # an LLMCallError, so it escaped every handler in lge/llm/run.py and
    # killed the whole run instead of failing one firm. Same for a choice
    # whose message carries no content (a provider-side cut-off).
    choices = payload.get("choices")
    if not choices:
        err = payload.get("error")
        detail = err.get("message") if isinstance(err, dict) else err
        raise LLMCallError(f"no choices in response: {str(detail or payload)[:500]}")

    content = choices[0].get("message", {}).get("content")
    if content is None:
        finish = choices[0].get("finish_reason") or choices[0].get("native_finish_reason")
        raise LLMCallError(f"empty content in response (finish_reason={finish!r})")

    usage = payload.get("usage")
    return LLMResponse(content=content, usage=usage, raw=payload)
