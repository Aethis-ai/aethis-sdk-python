"""Sync client tests — mirrors the async test surface."""

from __future__ import annotations

import json

import httpx
import pytest

from aethis_sdk import (
    Aethis,
    AethisAPIError,
    AethisUnavailable,
    DecideResponse,
    SchemaResponse,
)

from tests.conftest import make_decide_response, make_schema_response


class TestDecide:
    def test_returns_parsed_response_on_200(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            assert request.url.path == "/api/v1/public/decide"
            body = json.loads(request.content)
            assert body["ruleset_id"] == "test_ruleset:v1"
            assert body["field_values"] == {"age": 25}
            return httpx.Response(200, json=make_decide_response(decision="eligible"))

        with Aethis(
            api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            resp = client.decide("test_ruleset:v1", {"age": 25})

        assert isinstance(resp, DecideResponse)
        assert resp.decision == "eligible"
        assert call_count == 1

    def test_sends_api_key_header(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["x-api-key"] == "my-secret-key"
            return httpx.Response(200, json=make_decide_response())

        with Aethis(
            api_key="my-secret-key",
            base_url="http://test",
            transport=httpx.MockTransport(handler),
        ) as client:
            client.decide("ruleset:v1", {})

    def test_retries_once_on_500_then_succeeds(self):
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(500)
            return httpx.Response(200, json=make_decide_response(decision="eligible"))

        with Aethis(
            api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            resp = client.decide("ruleset:v1", {})

        assert resp.decision == "eligible"
        assert call_count == 2

    def test_raises_unavailable_after_retries(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        with Aethis(
            api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(AethisUnavailable):
                client.decide("ruleset:v1", {})

    def test_404_raises_api_error_with_status(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "Ruleset not found"})

        with Aethis(
            api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            with pytest.raises(AethisAPIError) as exc_info:
                client.decide("nonexistent:v1", {})
        assert exc_info.value.status_code == 404


class TestGetSchema:
    def test_returns_parsed_response(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/public/rulesets/b:v1/schema"
            return httpx.Response(200, json=make_schema_response(ruleset_id="b:v1"))

        with Aethis(
            api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
        ) as client:
            resp = client.get_schema("b:v1")
        assert isinstance(resp, SchemaResponse)
        assert resp.ruleset_id == "b:v1"


class TestConfig:
    def test_https_enforced_on_non_local_url(self):
        with pytest.raises(ValueError, match="HTTPS"):
            Aethis(api_key="k", base_url="http://api.example.com")

    def test_raises_if_used_outside_context(self):
        client = Aethis(
            api_key="k",
            base_url="http://test",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})),
        )
        with pytest.raises(RuntimeError, match="not open"):
            client.decide("b:v1", {})
