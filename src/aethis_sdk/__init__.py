"""Official Python SDK for the Aethis developer API."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from aethis_sdk.client import Aethis, AsyncAethis
from aethis_sdk.errors import (
    AethisAPIError,
    AethisError,
    AethisTimeout,
    AethisUnavailable,
)
from aethis_sdk.models import (
    DecideResponse,
    Decision,
    NextQuestion,
    SchemaField,
    SchemaResponse,
    SectionResult,
    SectionStatus,
)
from aethis_sdk.session import DecisionSession, SessionStatus, SyncDecisionSession

try:
    __version__ = _pkg_version("aethis-sdk")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = [
    "__version__",
    "Aethis",
    "AsyncAethis",
    "AethisError",
    "AethisAPIError",
    "AethisUnavailable",
    "AethisTimeout",
    "DecideResponse",
    "Decision",
    "NextQuestion",
    "SchemaField",
    "SchemaResponse",
    "SectionResult",
    "SectionStatus",
    "DecisionSession",
    "SyncDecisionSession",
    "SessionStatus",
]
