"""Official Python SDK for the Aethis developer API."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

from aethis_sdk.client import Aethis, AsyncAethis
from aethis_sdk.errors import (
    AethisAPIError,
    AethisAuthError,
    AethisContractViolation,
    AethisError,
    AethisFieldErrors,
    AethisPermissionError,
    AethisRateLimitError,
    AethisReplayIdentityError,
    AethisTimeout,
    AethisUnavailable,
)
from aethis_sdk.identity import ContentIdentity, ReplayIdentity
from aethis_sdk.models import (
    ClassUsage,
    DecideResponse,
    Decision,
    DecisionExplanation,
    ExplainCriterion,
    ExplainResponse,
    ExplanationCriterion,
    ExplanationGroup,
    FieldNote,
    GraphResponse,
    NextQuestion,
    RateLimit,
    RollingUsage,
    RulebookSchemaResponse,
    RulesetGraph,
    RulesetListItem,
    RulesetSummary,
    SchemaField,
    SchemaResponse,
    SectionResult,
    SectionStatus,
    SourceQuote,
    SourceReference,
    UsageResponse,
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
    "AethisAuthError",
    "AethisContractViolation",
    "AethisFieldErrors",
    "AethisPermissionError",
    "AethisRateLimitError",
    "AethisReplayIdentityError",
    "AethisUnavailable",
    "AethisTimeout",
    "ClassUsage",
    "ContentIdentity",
    "DecideResponse",
    "Decision",
    "DecisionExplanation",
    "ExplainCriterion",
    "ExplainResponse",
    "ExplanationCriterion",
    "ExplanationGroup",
    "FieldNote",
    "GraphResponse",
    "NextQuestion",
    "RateLimit",
    "ReplayIdentity",
    "RollingUsage",
    "RulebookSchemaResponse",
    "RulesetGraph",
    "RulesetListItem",
    "RulesetSummary",
    "SchemaField",
    "SchemaResponse",
    "SectionResult",
    "SectionStatus",
    "SourceQuote",
    "SourceReference",
    "UsageResponse",
    "DecisionSession",
    "SyncDecisionSession",
    "SessionStatus",
]
