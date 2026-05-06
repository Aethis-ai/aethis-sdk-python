"""Sync and async HTTP clients for the Aethis public API."""

from __future__ import annotations

from typing import Any

import httpx

from aethis_sdk._base import (
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    MAX_RETRIES,
    build_headers,
    build_httpx_kwargs,
    classify_response,
    is_5xx,
    logger,
    unavailable_after_retries,
    validate_base_url,
)
from aethis_sdk.errors import AethisError, AethisTimeout
from aethis_sdk.models import DecideResponse, SchemaResponse

DECIDE_PATH = "/api/v1/public/decide"
WHOAMI_PATH = "/api/v1/public/me"


def _schema_path(ruleset_id: str) -> str:
    return f"/api/v1/public/rulesets/{ruleset_id}/schema"


def _explain_path(ruleset_id: str) -> str:
    return f"/api/v1/public/rulesets/{ruleset_id}/explain"


def _source_path(ruleset_id: str) -> str:
    return f"/api/v1/public/rulesets/{ruleset_id}/source"


def _decide_payload(
    ruleset_id: str,
    field_values: dict[str, Any],
    include_trace: bool,
) -> dict[str, Any]:
    return {
        "ruleset_id": ruleset_id,
        "field_values": field_values,
        "include_trace": include_trace,
    }


class Aethis:
    """Synchronous client for the Aethis public API.

    Usage::

        with Aethis(api_key="...") as client:
            response = client.decide("ruleset:v1", {"age": 25})
            print(response.decision)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        iam_token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = validate_base_url(base_url, is_test=transport is not None)
        self._headers = build_headers(api_key, iam_token)
        self._timeout = timeout
        self._transport = transport
        self._client: httpx.Client | None = None

    def __enter__(self) -> "Aethis":
        self._client = httpx.Client(
            **build_httpx_kwargs(self._base_url, self._headers, self._timeout, self._transport)
        )
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # Public API --------------------------------------------------------

    def decide(
        self,
        ruleset_id: str,
        field_values: dict[str, Any],
        include_trace: bool = False,
    ) -> DecideResponse:
        """Evaluate a ruleset against the supplied field values."""
        resp = self._request("POST", DECIDE_PATH, json=_decide_payload(ruleset_id, field_values, include_trace))
        return DecideResponse.model_validate(resp.json())

    def get_schema(self, ruleset_id: str) -> SchemaResponse:
        """Return the field schema for a ruleset."""
        resp = self._request("GET", _schema_path(ruleset_id))
        return SchemaResponse.model_validate(resp.json())

    def whoami(self) -> dict[str, Any]:
        """Return metadata about the current API key."""
        resp = self._request("GET", WHOAMI_PATH)
        return resp.json()

    def explain(self, ruleset_id: str) -> dict[str, Any]:
        """Return a human-readable explanation of a ruleset's rules."""
        resp = self._request("GET", _explain_path(ruleset_id))
        return resp.json()

    def get_source(self, ruleset_id: str) -> dict[str, Any]:
        """Return the source-text provenance for a ruleset."""
        resp = self._request("GET", _source_path(ruleset_id))
        return resp.json()

    # Internal ----------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("Client is not open. Use 'with Aethis(...) as client:'.")

        last_status: int | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = self._client.request(method, path, **kwargs)
            except httpx.TimeoutException as e:
                logger.error("Timeout on %s %s: %s", method, path, e)
                raise AethisTimeout("Aethis API request timed out") from e
            except httpx.HTTPError as e:
                logger.error("HTTP error on %s %s: %s", method, path, e)
                raise AethisError("Aethis API connection error") from e

            if not is_5xx(resp):
                classify_response(resp)
                return resp

            last_status = resp.status_code
            logger.warning(
                "Aethis API %d on %s (attempt %d/%d)",
                resp.status_code, path, attempt + 1, MAX_RETRIES + 1,
            )

        raise unavailable_after_retries(last_status or 500, MAX_RETRIES + 1)


class AsyncAethis:
    """Asynchronous client for the Aethis public API.

    Usage::

        async with AsyncAethis(api_key="...") as client:
            response = await client.decide("ruleset:v1", {"age": 25})
            print(response.decision)
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        iam_token: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = validate_base_url(base_url, is_test=transport is not None)
        self._headers = build_headers(api_key, iam_token)
        self._timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "AsyncAethis":
        self._client = httpx.AsyncClient(
            **build_httpx_kwargs(self._base_url, self._headers, self._timeout, self._transport)
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # Public API --------------------------------------------------------

    async def decide(
        self,
        ruleset_id: str,
        field_values: dict[str, Any],
        include_trace: bool = False,
    ) -> DecideResponse:
        """Evaluate a ruleset against the supplied field values."""
        resp = await self._request("POST", DECIDE_PATH, json=_decide_payload(ruleset_id, field_values, include_trace))
        return DecideResponse.model_validate(resp.json())

    async def get_schema(self, ruleset_id: str) -> SchemaResponse:
        """Return the field schema for a ruleset."""
        resp = await self._request("GET", _schema_path(ruleset_id))
        return SchemaResponse.model_validate(resp.json())

    async def whoami(self) -> dict[str, Any]:
        """Return metadata about the current API key."""
        resp = await self._request("GET", WHOAMI_PATH)
        return resp.json()

    async def explain(self, ruleset_id: str) -> dict[str, Any]:
        """Return a human-readable explanation of a ruleset's rules."""
        resp = await self._request("GET", _explain_path(ruleset_id))
        return resp.json()

    async def get_source(self, ruleset_id: str) -> dict[str, Any]:
        """Return the source-text provenance for a ruleset."""
        resp = await self._request("GET", _source_path(ruleset_id))
        return resp.json()

    # Internal ----------------------------------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self._client is None:
            raise RuntimeError("Client is not open. Use 'async with AsyncAethis(...) as client:'.")

        last_status: int | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await self._client.request(method, path, **kwargs)
            except httpx.TimeoutException as e:
                logger.error("Timeout on %s %s: %s", method, path, e)
                raise AethisTimeout("Aethis API request timed out") from e
            except httpx.HTTPError as e:
                logger.error("HTTP error on %s %s: %s", method, path, e)
                raise AethisError("Aethis API connection error") from e

            if not is_5xx(resp):
                classify_response(resp)
                return resp

            last_status = resp.status_code
            logger.warning(
                "Aethis API %d on %s (attempt %d/%d)",
                resp.status_code, path, attempt + 1, MAX_RETRIES + 1,
            )

        raise unavailable_after_retries(last_status or 500, MAX_RETRIES + 1)
