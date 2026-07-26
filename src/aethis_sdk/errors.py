"""Exception hierarchy for the Aethis SDK."""

from __future__ import annotations

# The two access boundaries a caller can hit. Surfaced on auth failures so a
# 401/403 says *which* door was closed, not merely that one was.
BOUNDARY_EVALUATION = "evaluation"
BOUNDARY_AUTHORING = "authoring"

DEVELOPER_ACCESS_URL = "https://aethis.ai/developer-access"


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

    ``boundary`` names which access boundary the call hit —
    ``"evaluation"`` (the no-key decision surface) or ``"authoring"`` (the
    invite-only publishing surface). ``None`` when the failure is not an
    access failure.
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
        boundary: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail
        self.body = body
        self.reason_code = reason_code
        self.missing_permissions = missing_permissions or []
        self.hint = hint
        self.boundary = boundary


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
    ``boundary`` is ``"authoring"``: evaluation endpoints do not 401 for a
    missing key during the developer beta, so a 401 means the call crossed
    into the invite-only surface.
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


class AethisContractViolation(AethisError):
    """Raised when a 2xx response contradicts the published API contract.

    The engine guarantees that a non-empty ``field_errors`` always accompanies
    ``decision == "undetermined"``, and that no embedded copy of the verdict
    (``explanation.decision``, ``trace.status``) contradicts it. A payload that
    breaks that guarantee did not come from a conforming engine — a stale
    build, a caching proxy, or a mock. The SDK refuses to parse it into a model
    a caller would then act on, rather than surfacing a positive verdict that
    was computed beside blocking input errors.
    """


class AethisFieldErrors(AethisError):
    """Raised by :meth:`DecideResponse.raise_for_blocking_errors` when a
    decision carries blocking input errors.

    ``field_errors`` maps field id to the engine's message. The decision that
    produced it is always ``undetermined`` — this exception exists so a caller
    can treat "the engine could not use some of my inputs" as a failure rather
    than as a branch it might forget to write.
    """

    def __init__(self, message: str, field_errors: dict[str, str]) -> None:
        super().__init__(message, status_code=None)
        self.field_errors = dict(field_errors)


class AethisReplayIdentityError(AethisError):
    """Raised when a response's replay identity is required but unresolved.

    ``missing`` names the parts that were absent (e.g. ``["ruleset_version"]``).
    Raised only by the explicit ``require_*`` accessors — reading the optional
    attributes never raises.
    """

    def __init__(self, message: str, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.missing = missing or []
