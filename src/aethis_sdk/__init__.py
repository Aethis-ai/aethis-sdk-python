"""Official Python SDK for the Aethis developer API."""

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

__version__ = "0.1.0"

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
