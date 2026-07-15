"""Exception hierarchy for the Aethis SDK."""

from __future__ import annotations


class AethisError(Exception):
    """Base exception for all Aethis SDK failures.

    ``detail`` and ``body`` carry the parsed error payload when the failure
    originated from an API response — ``detail`` is the ``detail`` field the
    API returns on 4xx (a string, FastAPI's list-of-errors on a 422, or the
    structured envelope object the public API returns on 401/403/429), and
    ``body`` is the full decoded JSON body. Both are ``None`` for failures that
    never reached a response (timeouts, connection errors).

    ``reason_code``, ``missing_permissions`` and ``hint`` are lifted out of the
    structured 401/403/429 envelope when present, so callers can branch on the
    machine-readable reason without re-parsing ``body``. They are ``None`` /
    empty for responses that don't carry them.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        detail: object | None = None,
        body: object | None = None,
        reason_code: str | None = None,
        missing_permissions: list[str] | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail
        self.body = body
        self.reason_code = reason_code
        self.missing_permissions = missing_permissions or []
        self.hint = hint


class AethisAPIError(AethisError):
    """Raised on 4xx responses from the Aethis API.

    Indicates a client error: bad request, auth failure, missing ruleset, etc.
    The status-specific subclasses below (:class:`AethisAuthError`,
    :class:`AethisPermissionError`, :class:`AethisRateLimitError`) are raised
    for 401 / 403 / 429; every one of them is an ``AethisAPIError``, so
    ``except AethisAPIError`` keeps catching them all.
    """


class AethisAuthError(AethisAPIError):
    """Raised on a 401 from the Aethis API — missing, invalid, or expired key.

    ``reason_code`` is one of ``missing_api_key`` / ``invalid_api_key`` /
    ``api_key_expired`` when the response carries the structured envelope.
    """


class AethisPermissionError(AethisAPIError):
    """Raised on a 403 from the Aethis API — the key lacks a required scope.

    ``missing_permissions`` lists the scope(s) the endpoint required and the
    key did not hold; ``hint`` carries the human-readable next step; and
    ``reason_code`` is ``denied_missing_permission`` for the scope-gate case.
    """


class AethisRateLimitError(AethisAPIError):
    """Raised on a 429 from the Aethis API — a rate/quota limit was exceeded.

    ``reason_code`` is ``daily_quota_exceeded`` for the quota case; the
    envelope's ``category``, ``tier`` and ``limit`` are available on ``detail``.
    """


class AethisUnavailable(AethisError):
    """Raised when the Aethis API returns 5xx after retries are exhausted."""

    def __init__(self, message: str = "Aethis API unavailable after retries") -> None:
        super().__init__(message, status_code=503)


class AethisTimeout(AethisError):
    """Raised when a request to the Aethis API times out."""

    def __init__(self, message: str = "Aethis API request timed out") -> None:
        super().__init__(message, status_code=None)
