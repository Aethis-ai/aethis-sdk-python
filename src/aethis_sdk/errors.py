"""Exception hierarchy for the Aethis SDK."""

from __future__ import annotations


class AethisError(Exception):
    """Base exception for all Aethis SDK failures.

    ``detail`` and ``body`` carry the parsed error payload when the failure
    originated from an API response — ``detail`` is the ``detail`` field the
    API returns on 4xx (a string, or FastAPI's list-of-errors on a 422), and
    ``body`` is the full decoded JSON body. Both are ``None`` for failures that
    never reached a response (timeouts, connection errors).
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        detail: object | None = None,
        body: object | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail
        self.body = body


class AethisAPIError(AethisError):
    """Raised on 4xx responses from the Aethis API.

    Indicates a client error: bad request, auth failure, missing ruleset, etc.
    """


class AethisUnavailable(AethisError):
    """Raised when the Aethis API returns 5xx after retries are exhausted."""

    def __init__(self, message: str = "Aethis API unavailable after retries") -> None:
        super().__init__(message, status_code=503)


class AethisTimeout(AethisError):
    """Raised when a request to the Aethis API times out."""

    def __init__(self, message: str = "Aethis API request timed out") -> None:
        super().__init__(message, status_code=None)
