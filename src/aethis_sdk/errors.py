"""Exception hierarchy for the Aethis SDK."""

from __future__ import annotations


class AethisError(Exception):
    """Base exception for all Aethis SDK failures."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AethisAPIError(AethisError):
    """Raised on 4xx responses from the Aethis API.

    Indicates a client error: bad request, auth failure, missing bundle, etc.
    """


class AethisUnavailable(AethisError):
    """Raised when the Aethis API returns 5xx after retries are exhausted."""

    def __init__(self, message: str = "Aethis API unavailable after retries") -> None:
        super().__init__(message, status_code=503)


class AethisTimeout(AethisError):
    """Raised when a request to the Aethis API times out."""

    def __init__(self, message: str = "Aethis API request timed out") -> None:
        super().__init__(message, status_code=None)
