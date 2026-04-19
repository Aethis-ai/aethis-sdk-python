"""Async client tests — uses httpx.MockTransport to avoid real HTTP."""

from __future__ import annotations

import json

import httpx
import pytest

from aethis_sdk import (
    AethisAPIError,
    AethisUnavailable,
    AsyncAethis,
    DecideResponse,
    SchemaResponse,
)

from tests.conftest import make_decide_response, make_schema_response


class TestDecide:
    async def test_returns_parsed_response_on_200(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            assert request.url.path == "/api/v1/public/decide"
            assert request.method == "POST"
            body = json.loads(request.content)
            assert body["bundle_id"] == "test_bundle:v1"
            assert body["field_values"] == {"age": 25}
            return httpx.Response(200, json=make_decide_response(decision="eligible"))

        async with AsyncAethis(
            api_key="test-key",
            base_url="http://test",
            transport=httpx.MockTransport(handler),
        ) as client:
            resp = await client.decide("test_bundle:v1", {"age": 25})

        assert isinstance(resp, DecideResponse)
        assert resp.decision == "eligible"
        assert call_count == 1

    async def test_sends_api_key_header(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["x-api-key"] == "my-secret-key"
            return httpx.Response(200, json=make_decide_response())

        async with AsyncAethis(
            api_key="my-secret-key",
            base_url="http://test",
            transport=httpx.MockTransport(handler),
        ) as client:
            await client.decide("bundle:v1", {})

    async def test_sends_iam_bearer_when_configured(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "Bearer iam-token-xyz"
            assert request.headers["x-api-key"] == "k"
            return httpx.Response(200, json=make_decide_response())

        async with AsyncAethis(
            api_key="k",
            base_url="http://test",
            iam_token="iam-token-xyz",
            transport=httpx.MockTransport(handler),
        ) as client:
            await client.decide("bundle:v1", {})

    async def test_sends_include_trace(self):
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["include_trace"] is True
            return httpx.Response(200, json=make_decide_response())

        async with AsyncAethis(
            api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            await client.decide("bundle:v1", {}, include_trace=True)

    async def test_404_raises_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Bundle not found"})

        async with AsyncAethis(
            api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(AethisAPIError, match="404") as exc_info:
                await client.decide("nonexistent:v1", {})
        assert exc_info.value.status_code == 404

    async def test_401_raises_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "Invalid API key"})

        async with AsyncAethis(
            api_key="bad", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(AethisAPIError, match="401"):
                await client.decide("bundle:v1", {})

    async def test_retries_once_on_500_then_succeeds(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(500, json={"detail": "Internal error"})
            return httpx.Response(200, json=make_decide_response(decision="eligible"))

        async with AsyncAethis(
            api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            resp = await client.decide("bundle:v1", {})

        assert resp.decision == "eligible"
        assert call_count == 2

    async def test_raises_unavailable_after_retries_exhausted(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"detail": "Internal error"})

        async with AsyncAethis(
            api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(AethisUnavailable):
                await client.decide("bundle:v1", {})


class TestGetSchema:
    async def test_returns_parsed_response_on_200(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/public/bundles/test_bundle:v1/schema"
            assert request.method == "GET"
            return httpx.Response(200, json=make_schema_response())

        async with AsyncAethis(
            api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            resp = await client.get_schema("test_bundle:v1")

        assert isinstance(resp, SchemaResponse)
        assert resp.bundle_id == "test_bundle:v1"
        assert len(resp.fields) == 3
        assert resp.fields[0].field_id == "age"
        assert resp.fields[0].field_type == "integer"

    async def test_404_raises_api_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Not found"})

        async with AsyncAethis(
            api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(AethisAPIError, match="404"):
                await client.get_schema("nonexistent:v1")


class TestReadOnlyEndpoints:
    async def test_whoami(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/public/me"
            return httpx.Response(200, json={"tenant_id": "t1", "tier": "internal"})

        async with AsyncAethis(
            api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            resp = await client.whoami()
        assert resp == {"tenant_id": "t1", "tier": "internal"}

    async def test_explain(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/public/bundles/b:v1/explain"
            return httpx.Response(200, json={"sections": []})

        async with AsyncAethis(
            api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            resp = await client.explain("b:v1")
        assert resp == {"sections": []}

    async def test_get_source(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/public/bundles/b:v1/source"
            return httpx.Response(200, json={"text": "legislation excerpt"})

        async with AsyncAethis(
            api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            resp = await client.get_source("b:v1")
        assert resp == {"text": "legislation excerpt"}


class TestConfig:
    def test_https_enforced_on_non_local_url(self):
        with pytest.raises(ValueError, match="HTTPS"):
            AsyncAethis(api_key="k", base_url="http://api.example.com")

    def test_http_allowed_for_localhost(self):
        client = AsyncAethis(api_key="k", base_url="http://localhost:8080")
        assert client._base_url == "http://localhost:8080"

    def test_http_allowed_with_mock_transport(self):
        client = AsyncAethis(
            api_key="k",
            base_url="http://test",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
        )
        assert client._base_url == "http://test"

    async def test_raises_if_used_outside_context(self):
        client = AsyncAethis(
            api_key="k",
            base_url="http://test",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
        )
        with pytest.raises(RuntimeError, match="not open"):
            await client.decide("b:v1", {})
