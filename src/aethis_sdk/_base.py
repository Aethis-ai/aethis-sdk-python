"""Shared client helpers — URL/header prep, response classification."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from aethis_sdk.errors import (
    AethisAPIError,
    AethisAuthError,
    AethisPermissionError,
    AethisRateLimitError,
    AethisUnavailable,
)

logger = logging.getLogger("aethis_sdk")

DEFAULT_BASE_URL = "https://api.aethis.ai"
DEFAULT_TIMEOUT = 5.0
MAX_RETRIES = 1

# Status codes the public API answers with a structured error envelope
# (``detail`` is an object carrying ``reason_code`` etc.), mapped to the typed
# exception the SDK raises. Any other 4xx falls back to ``AethisAPIError``.
_TYPED_4XX = {
    401: AethisAuthError,
    403: AethisPermissionError,
    429: AethisRateLimitError,
}


def validate_base_url(base_url: str, is_test: bool) -> str:
    """Enforce HTTPS for non-local base URLs. Allow HTTP for localhost or tests."""
    is_local = "localhost" in base_url or "127.0.0.1" in base_url
    if not base_url.startswith("https://") and not is_local and not is_test:
        raise ValueError("base_url must use HTTPS (http:// is only allowed for localhost)")
    return base_url.rstrip("/")


def build_headers(api_key: str | None, iam_token: str | None) -> dict[str, str]:
    """Construct default headers. ``iam_token`` is for Cloud Run service-to-service auth.

    During the developer beta, evaluation endpoints (``/decide``, ``/schema``,
    ``/explain``) accept anonymous calls, so ``api_key`` is optional. When
    omitted, no ``x-api-key`` header is sent and authoring endpoints will
    return 401.
    """
    headers: dict[str, str] = {}
    if api_key is not None:
        headers["x-api-key"] = api_key
    if iam_token:
        headers["Authorization"] = f"Bearer {iam_token}"
    return headers


def classify_response(resp: httpx.Response) -> None:
    """Raise a typed ``AethisAPIError`` on 4xx. Caller handles 5xx retries.

    401 / 403 / 429 map to :class:`AethisAuthError` / :class:`AethisPermissionError`
    / :class:`AethisRateLimitError` and lift ``reason_code`` / ``missing_permissions``
    / ``hint`` out of the structured error envelope the public API returns
    (``{"detail": {"error", "reason_code", ...}}``). Any other 4xx raises the
    base :class:`AethisAPIError`. 2xx responses pass through silently.
    """
    if resp.status_code < 400:
        return
    if resp.status_code < 500:
        body: object | None
        detail: object | None
        try:
            body = resp.json()
            detail = body.get("detail") if isinstance(body, dict) else None
        except Exception:
            body = None
            detail = None

        reason_code, missing_permissions, hint = _extract_envelope_fields(detail)

        logger.error("Aethis API %d on %s: %s", resp.status_code, resp.request.url.path, detail)
        message = f"Aethis API returned {resp.status_code}"
        if reason_code:
            message = f"{message}: {reason_code}"
        elif detail:
            message = f"{message}: {detail}"

        error_cls = _TYPED_4XX.get(resp.status_code, AethisAPIError)
        raise error_cls(
            message,
            status_code=resp.status_code,
            detail=detail,
            body=body,
            reason_code=reason_code,
            missing_permissions=missing_permissions,
            hint=hint,
        )


def _extract_envelope_fields(
    detail: object | None,
) -> tuple[str | None, list[str] | None, str | None]:
    """Pull ``reason_code`` / ``missing_permissions`` / ``hint`` from a structured
    error envelope's ``detail`` object. Returns ``(None, None, None)`` when the
    detail is a plain string or FastAPI validation list rather than the envelope.
    """
    if not isinstance(detail, dict):
        return None, None, None
    reason_code = detail.get("reason_code")
    missing = detail.get("missing_permissions")
    hint = detail.get("hint")
    return (
        str(reason_code) if reason_code is not None else None,
        [str(p) for p in missing] if isinstance(missing, list) else None,
        str(hint) if hint is not None else None,
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
