"""Tests for usage() + X-RateLimit capture (epic aethis-workspace#552)."""

from __future__ import annotations

import httpx
import pytest

from aethis_sdk import Aethis, AsyncAethis, RateLimit, UsageResponse

_USAGE = {
    "tier": "free",
    "classes": [
        {"class": "generate", "used": 3, "limit": 200, "remaining": 197, "reset": 1800000000},
        {"class": "read", "used": 50, "limit": 100000, "remaining": 99950, "reset": 1800000000},
    ],
    "rolling": {"last_7_days": {"generate": 11}, "last_30_days": {"generate": 11}},
}

_RL_HEADERS = {
    "X-RateLimit-Class": "read",
    "X-RateLimit-Limit": "100000",
    "X-RateLimit-Remaining": "99997",
    "X-RateLimit-Reset": "1800000000",
}


def test_usage_returns_per_class():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/public/usage"
        return httpx.Response(200, json=_USAGE)

    with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
        u = client.usage()

    assert isinstance(u, UsageResponse)
    assert u.tier == "free"
    by_class = {c.operation_class: c for c in u.classes}
    assert by_class["generate"].remaining == 197
    assert by_class["generate"].limit == 200
    assert u.rolling.last_30_days["generate"] == 11


def test_rate_limit_captured_from_headers():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_USAGE, headers=_RL_HEADERS)

    with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
        assert client.rate_limit is None  # nothing seen yet
        client.usage()
        rl = client.rate_limit

    assert isinstance(rl, RateLimit)
    assert rl.operation_class == "read"
    assert rl.remaining == 99997
    assert rl.limit == 100000


def test_rate_limit_none_when_headers_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_USAGE)

    with Aethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
        client.usage()
        assert client.rate_limit is None


@pytest.mark.asyncio
async def test_async_usage_and_rate_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_USAGE, headers=_RL_HEADERS)

    async with AsyncAethis(api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)) as client:
        u = await client.usage()
        rl = client.rate_limit

    assert u.tier == "free"
    assert rl is not None and rl.operation_class == "read"
