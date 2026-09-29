"""OpenRouter client: request shape, retry/backoff on 429 and 5xx honouring
Retry-After, timeout retry, and that the API key never leaks into anything
we can inspect besides the Authorization header itself."""

from __future__ import annotations

import httpx
import pytest
import respx

from lge.llm.client import OPENROUTER_URL, LLMCallError, call_openrouter

pytestmark = pytest.mark.asyncio

_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {"name": "x", "strict": True, "schema": {}},
}


def _ok_response(content: str = "{}") -> dict:
    return {
        "id": "gen-1",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


async def test_request_shape_url_headers_body():
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(OPENROUTER_URL).mock(
            return_value=httpx.Response(200, json=_ok_response())
        )
        async with httpx.AsyncClient() as client:
            resp = await call_openrouter(
                client,
                api_key="sk-or-secret-value",
                model="anthropic/claude-haiku-4.5",
                system="sys prompt",
                user="user prompt",
                response_format=_RESPONSE_FORMAT,
                max_tokens=500,
                timeout_s=5,
                referer="https://legalsoft.com",
                title="Legal Soft Lead Engine",
            )

        assert route.call_count == 1
        request = route.calls[0].request
        assert str(request.url) == OPENROUTER_URL
        assert request.headers["Authorization"] == "Bearer sk-or-secret-value"
        assert request.headers["HTTP-Referer"] == "https://legalsoft.com"
        assert request.headers["X-Title"] == "Legal Soft Lead Engine"

        import json

        body = json.loads(request.content)
        assert body["model"] == "anthropic/claude-haiku-4.5"
        assert body["response_format"] == _RESPONSE_FORMAT
        assert body["max_tokens"] == 500
        assert body["messages"][0] == {"role": "system", "content": "sys prompt"}
        assert body["messages"][1] == {"role": "user", "content": "user prompt"}
        assert resp.content == "{}"
        assert resp.usage == {"prompt_tokens": 10, "completion_tokens": 5}


async def test_key_never_appears_in_url_or_body():
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(OPENROUTER_URL).mock(
            return_value=httpx.Response(200, json=_ok_response())
        )
        async with httpx.AsyncClient() as client:
            await call_openrouter(
                client,
                api_key="sk-or-topsecret",
                model="m",
                system="s",
                user="u",
                response_format=_RESPONSE_FORMAT,
                max_tokens=10,
                timeout_s=5,
                referer="https://legalsoft.com",
                title="t",
            )
        request = route.calls[0].request
        assert "sk-or-topsecret" not in str(request.url)
        assert "sk-or-topsecret" not in request.content.decode()


async def test_429_with_retry_after_is_honoured_then_succeeds(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("lge.llm.client.asyncio.sleep", fake_sleep)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(OPENROUTER_URL)
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "2.5"}, text="rate limited"),
            httpx.Response(200, json=_ok_response('{"ok": true}')),
        ]
        async with httpx.AsyncClient() as client:
            resp = await call_openrouter(
                client,
                api_key="k",
                model="m",
                system="s",
                user="u",
                response_format=_RESPONSE_FORMAT,
                max_tokens=10,
                timeout_s=5,
                referer="r",
                title="t",
                max_retries=3,
                backoff_base_s=0.001,
                backoff_max_s=0.01,
            )
        assert route.call_count == 2
        assert sleeps == [2.5]
        assert resp.content == '{"ok": true}'


async def test_5xx_retried_up_to_max_retries_then_raises(monkeypatch):
    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr("lge.llm.client.asyncio.sleep", fake_sleep)

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(OPENROUTER_URL).mock(return_value=httpx.Response(503, text="down"))
        async with httpx.AsyncClient() as client:
            with pytest.raises(LLMCallError):
                await call_openrouter(
                    client,
                    api_key="k",
                    model="m",
                    system="s",
                    user="u",
                    response_format=_RESPONSE_FORMAT,
                    max_tokens=10,
                    timeout_s=5,
                    referer="r",
                    title="t",
                    max_retries=3,
                    backoff_base_s=0.001,
                    backoff_max_s=0.01,
                )
        assert route.call_count == 3  # max_retries total attempts, no more


async def test_400_is_not_retried():
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(OPENROUTER_URL).mock(return_value=httpx.Response(400, text="bad request"))
        async with httpx.AsyncClient() as client:
            with pytest.raises(LLMCallError):
                await call_openrouter(
                    client,
                    api_key="k",
                    model="m",
                    system="s",
                    user="u",
                    response_format=_RESPONSE_FORMAT,
                    max_tokens=10,
                    timeout_s=5,
                    referer="r",
                    title="t",
                    max_retries=3,
                )
        assert route.call_count == 1


async def test_200_with_error_body_and_no_choices_raises_llm_call_error():
    """OpenRouter answers 200 with a bare {"error": ...} for some upstream
    provider failures and for free-tier throttling. That used to raise
    KeyError out of the client, which lge/llm/run.py does not catch, so one
    bad firm killed the whole run."""
    body = {"error": {"message": "Upstream error from Nvidia: Service temporarily overloaded"}}
    with respx.mock(assert_all_called=True) as mock:
        mock.post(OPENROUTER_URL).mock(return_value=httpx.Response(200, json=body))
        async with httpx.AsyncClient() as client:
            with pytest.raises(LLMCallError) as exc:
                await call_openrouter(
                    client,
                    api_key="sk-or-secret-value",
                    model="m",
                    system="s",
                    user="u",
                    response_format=_RESPONSE_FORMAT,
                    max_tokens=10,
                    timeout_s=5,
                    referer="r",
                    title="t",
                )
    assert "no choices" in str(exc.value)
    assert "temporarily overloaded" in str(exc.value)
    assert "sk-or-secret-value" not in str(exc.value)


async def test_choice_with_null_content_raises_llm_call_error():
    """A provider-side cut-off returns a choice whose message content is
    null. Handing None to model_validate_json raises TypeError, not
    ValidationError, so it escapes the parse-retry path in run.py."""
    body = {
        "id": "gen-1",
        "choices": [{"index": 0, "finish_reason": "length", "message": {"content": None}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3000},
    }
    with respx.mock(assert_all_called=True) as mock:
        mock.post(OPENROUTER_URL).mock(return_value=httpx.Response(200, json=body))
        async with httpx.AsyncClient() as client:
            with pytest.raises(LLMCallError) as exc:
                await call_openrouter(
                    client,
                    api_key="sk-or-secret-value",
                    model="m",
                    system="s",
                    user="u",
                    response_format=_RESPONSE_FORMAT,
                    max_tokens=10,
                    timeout_s=5,
                    referer="r",
                    title="t",
                )
    assert "empty content" in str(exc.value)
    assert "length" in str(exc.value)
