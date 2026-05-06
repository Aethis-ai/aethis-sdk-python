"""Shared client helpers — URL/header prep, response classification."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from aethis_sdk.errors import AethisAPIError, AethisUnavailable

logger = logging.getLogger("aethis_sdk")

DEFAULT_BASE_URL = "https://api.aethis.ai"
DEFAULT_TIMEOUT = 5.0
MAX_RETRIES = 1


def validate_base_url(base_url: str, is_test: bool) -> str:
    """Enforce HTTPS for non-local base URLs. Allow HTTP for localhost or tests."""
    is_local = "localhost" in base_url or "127.0.0.1" in base_url
    if not base_url.startswith("https://") and not is_local and not is_test:
        raise ValueError("base_url must use HTTPS (http:// is only allowed for localhost)")
    return base_url.rstrip("/")


def build_headers(api_key: str | None, iam_token: str | None) -> dict[str, str]:
    """Construct default headers. ``iam_token`` is for Cloud Run service-to-service auth.

    During the developer beta, evaluation endpoints (``/decide``, ``/schema``,
    ``/explain``, ``/next_question``) accept anonymous calls, so ``api_key`` is
    optional. When omitted, no ``x-api-key`` header is sent and authoring
    endpoints will return 401.
    """
    headers: dict[str, str] = {}
    if api_key is not None:
        headers["x-api-key"] = api_key
    if iam_token:
        headers["Authorization"] = f"Bearer {iam_token}"
    return headers


def classify_response(resp: httpx.Response) -> None:
    """Raise ``AethisAPIError`` on 4xx. Caller is responsible for 5xx retry handling.

    2xx responses pass through silently.
    """
    if resp.status_code < 400:
        return
    if resp.status_code < 500:
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = ""
        logger.error("Aethis API %d on %s: %s", resp.status_code, resp.request.url.path, detail)
        raise AethisAPIError(
            f"Aethis API returned {resp.status_code}",
            status_code=resp.status_code,
        )


def unavailable_after_retries(status_code: int, attempts: int) -> AethisUnavailable:
    """Build the error raised when 5xx retries are exhausted."""
    return AethisUnavailable(
        f"Aethis API returned {status_code} after {attempts} attempt(s)"
    )


def is_5xx(resp: httpx.Response) -> bool:
    return resp.status_code >= 500


def build_httpx_kwargs(
    base_url: str,
    headers: dict[str, str],
    timeout: float,
    transport: Any | None,
) -> dict[str, Any]:
    """Shared kwargs for httpx.Client / httpx.AsyncClient construction."""
    kwargs: dict[str, Any] = {
        "base_url": base_url,
        "headers": headers,
        "timeout": timeout,
    }
    if transport is not None:
        kwargs["transport"] = transport
    return kwargs
