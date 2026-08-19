"""Pydantic response models for the Aethis public API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aethis_sdk.errors import (
    AethisContractViolation,
    AethisFieldErrors,
    AethisReplayIdentityError,
)
from aethis_sdk.identity import (
    ContentIdentity,
    ReplayIdentity,
    normalise_content_digest,
    normalise_identity_value,
)

Decision = Literal["eligible", "not_eligible", "undetermined"]
SectionStatus = Literal["satisfied", "not_satisfied", "pending"]

# The only verdict the engine may report beside blocking input errors.
_NON_TERMINAL_DECISION = "undetermined"


class FieldNote(BaseModel):
    """Structured guidance attached to a field being asked about.

    Mirrors the engine's ``FieldNoteOut``: author-provided rationale and legal
    background the navigator surfaces alongside a ``next_question`` so callers
    can render it to end users. ``metadata`` is loosely typed because callers
    attach domain-specific tags (``type``, ``section``, ``warning``, ...).
    """

    note_text: str
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class NextQuestion(BaseModel):
    """The next field the API recommends asking about."""

    field_id: str
    question: str
    weight: int
    notes: list[FieldNote] = Field(default_factory=list)


class SectionResult(BaseModel):
    """Per-section result for multi-section rulesets."""

    section_id: str
    ruleset_id: str | None = None
    status: SectionStatus


# ---------------------------------------------------------------------------
# Source provenance (engine contract: SourceReference / SourceQuote)
# ---------------------------------------------------------------------------


class SourceQuote(BaseModel):
    """The verbatim text a reference cites, with optional locating context.

    ``exact`` is verbatim text from the cited document — never a summary or a
    paraphrase. The engine verifies at publish time that it occurs in the
    fetched source whose digest is recorded on the parent reference, and fails
    the publish when it does not.
    """

    model_config = ConfigDict(extra="allow")

    exact: str
    prefix: str | None = None
    suffix: str | None = None


class SourceReference(BaseModel):
    """One publish-validated citation binding a criterion to its authority.

    Returned identically by ``GET /rulesets/{id}/explain`` and by
    ``POST /decide`` with ``include_explanation: true``. Every field is
    resolved and validated when the ruleset is published — a reference that
    cannot be fetched, digested, quoted verbatim and licensed blocks the
    publish, so a reference that reaches a caller has already been checked.

    ``schema_version`` is the wire-schema generation. It evolves additively:
    a future version adds optional fields without removing or retyping any of
    today's, so a consumer pinning ``schema_version >= 1`` keeps working. The
    model accepts unknown fields for exactly that reason.

    Provenance is not correctness: a reference records *what the rule cites*
    and that the citation was verified to exist, not that the rule's
    interpretation of it is right.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    source_id: str
    title: str
    authority: str
    url: str
    locator: str | None = None
    source_version: str | None = None
    source_date: str | None = None
    content_digest: str
    licence: str
    verified_at: datetime
    quote: SourceQuote
    media_type: str = "html"
    deep_link: str


# ---------------------------------------------------------------------------
# Explanations — two distinct shapes, deliberately modelled separately
# ---------------------------------------------------------------------------


class ExplanationCriterion(BaseModel):
    """One criterion inside a ``POST /decide`` explanation group."""

    model_config = ConfigDict(extra="allow")

    criterion_id: str
    title: str | None = None
    status: str | None = None
    supporting_facts: list[dict[str, Any]] | None = None
    source_refs: list[str] | None = None
    source_references: list[SourceReference] | None = None


class ExplanationGroup(BaseModel):
    """One group of criteria inside a ``POST /decide`` explanation."""

    model_config = ConfigDict(extra="allow")

    group: str | None = None
    status: str | None = None
    criteria: list[ExplanationCriterion] = Field(default_factory=list)


class DecisionExplanation(BaseModel):
    """The layered explanation ``POST /decide`` returns with
    ``include_explanation: true``.

    **This is not the ``/explain`` shape.** ``/decide`` nests criteria under
    ``groups[].criteria[]``; ``GET /rulesets/{id}/explain`` returns a flat
    ``criteria`` array (:class:`ExplainResponse`). The two endpoints share the
    :class:`SourceReference` DTO, not their envelopes — a fixture that serves
    the flat shape on both paths tests neither.
    """

    model_config = ConfigDict(extra="allow")

    decision: str | None = None
    decision_path: list[Any] | None = None
    groups: list[ExplanationGroup] = Field(default_factory=list)
    unused_facts: list[str] = Field(default_factory=list)

    def source_references(self) -> dict[str, list[SourceReference]]:
        """Every criterion's references, keyed by ``criterion_id``.

        Criteria with no references are omitted, so an empty mapping means
        "this decision cited nothing", not "no criteria fired".
        """
        found: dict[str, list[SourceReference]] = {}
        for group in self.groups:
            for criterion in group.criteria:
                if criterion.source_references:
                    found.setdefault(criterion.criterion_id, []).extend(criterion.source_references)
        return found


class ExplainCriterion(BaseModel):
    """One criterion from ``GET /rulesets/{ruleset_id}/explain``."""

    model_config = ConfigDict(extra="allow")

    criterion_id: str
    group: str | None = None
    title: str | None = None
    rule_text: str
    source_refs: list[str] | None = None
    source_references: list[SourceReference] | None = None


class ExplainResponse(BaseModel):
    """Response body from ``GET /api/v1/public/rulesets/{ruleset_id}/explain``.

    Carries the resolved immutable identity of the ruleset that was explained
    — never the caller's slug — so an explanation can be pinned to the exact
    content it describes. Criteria are **flat** here; see
    :class:`DecisionExplanation` for the ``/decide`` shape.
    """

    model_config = ConfigDict(extra="allow")

    ruleset_id: str
    slug: str | None = None
    ruleset_version: str | None = None
    content_digest: str | None = None
    criteria: list[ExplainCriterion] = Field(default_factory=list)

    @field_validator("ruleset_version", mode="before")
    @classmethod
    def _normalise(cls, value: Any) -> str | None:
        return normalise_identity_value(value)

    @field_validator("content_digest", mode="before")
    @classmethod
    def _normalise_digest(cls, value: Any) -> str | None:
        return normalise_content_digest(value)

    @property
    def content_identity(self) -> ContentIdentity | None:
        """The resolved identity, or ``None`` when any part is unresolved."""
        return _content_identity(self.ruleset_id, self.ruleset_version, self.content_digest)

    def require_content_identity(self) -> ContentIdentity:
        """The resolved identity, raising when any part is unresolved."""
        return _require_content_identity(self.ruleset_id, self.ruleset_version, self.content_digest, "explanation")

    def source_references(self) -> dict[str, list[SourceReference]]:
        """Every criterion's references, keyed by ``criterion_id``."""
        return {c.criterion_id: c.source_references for c in self.criteria if c.source_references}


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------


def _content_identity(
    ruleset_id: str | None,
    ruleset_version: str | None,
    content_digest: str | None,
) -> ContentIdentity | None:
    if not (ruleset_id and ruleset_version and content_digest):
        return None
    return ContentIdentity(
        ruleset_id=ruleset_id,
        ruleset_version=ruleset_version,
        content_digest=content_digest,
    )


def _missing_identity_parts(**parts: str | None) -> list[str]:
    return [name for name, value in parts.items() if not value]


def _require_content_identity(
    ruleset_id: str | None,
    ruleset_version: str | None,
    content_digest: str | None,
    what: str,
) -> ContentIdentity:
    identity = _content_identity(ruleset_id, ruleset_version, content_digest)
    if identity is not None:
        return identity
    missing = _missing_identity_parts(
        ruleset_id=ruleset_id,
        ruleset_version=ruleset_version,
        content_digest=content_digest,
    )
    raise AethisReplayIdentityError(
        f"This {what} has no resolved content identity: {', '.join(missing)} "
        f"{'is' if len(missing) == 1 else 'are'} unresolved. A published leaf ruleset always "
        "resolves all three; an unresolved identity means the response came from a rulebook "
        "call, an artefact published before immutable versions, or a non-conforming engine. "
        "Do not record it as a replayable reference.",
        missing=missing,
    )


class DecideResponse(BaseModel):
    """Response body from ``POST /api/v1/public/decide``.

    Carries either ``ruleset_id`` (single-ruleset decide) or ``rulebook_id``
    (composed multi-ruleset rulebook decide). ``slug`` echoes whichever
    identifier was used as a slug — opaque ``rb_*`` ids leave it ``None``.

    ## Replay identity

    For a published leaf ruleset the engine always resolves ``ruleset_id``,
    ``ruleset_version`` and ``content_digest`` from the stored publication.
    Where it cannot (a rulebook call, until composed identity lands), the wire
    reports the literal string ``"unknown"`` — which this model normalises to
    ``None``. There is deliberately **no** ``"unknown"`` default: a caller can
    never read a placeholder that looks like a version. Use
    :attr:`replay_identity` to test for one, or
    :meth:`require_replay_identity` to demand one.

    ## Blocking errors

    Every ``field_errors`` entry is blocking, and the engine forces
    ``decision == "undetermined"`` whenever any is present. This model enforces
    that at the parse boundary — sync, async and session paths all validate
    through it — so a response asserting a positive or negative verdict beside
    blocking errors raises
    :class:`~aethis_sdk.errors.AethisContractViolation` instead of becoming an
    object a caller can act on. Read :attr:`has_blocking_errors`; never infer
    success from the absence of ``next_question``.
    """

    decision: Decision
    ruleset_id: str | None = None
    rulebook_id: str | None = None
    slug: str | None = None
    ruleset_version: str | None = None
    # Only a well-formed `sha256:<64 lowercase hex>` survives; anything else
    # (an unresolved sentinel, `md5:...`, a truncated or non-hex value)
    # normalises to None rather than being carried into an audit record.
    content_digest: str | None = None
    engine_version: str | None = None
    decision_id: str | None = None
    inputs_hash: str | None = None
    decision_time: str | None = None
    fields_evaluated: int = 0
    fields_provided: int = 0
    missing_fields: list[str] | None = None
    next_question: NextQuestion | None = None
    optimal_path: list[NextQuestion] | None = None
    field_errors: dict[str, str] | None = None
    trace: dict[str, Any] | None = None
    explanation: dict[str, Any] | None = None
    section_results: list[SectionResult] | None = None
    graph_overlay: dict[str, Any] | None = None

    @field_validator(
        "ruleset_id",
        "ruleset_version",
        "engine_version",
        "decision_id",
        "inputs_hash",
        mode="before",
    )
    @classmethod
    def _normalise(cls, value: Any) -> str | None:
        return normalise_identity_value(value)

    @field_validator("content_digest", mode="before")
    @classmethod
    def _normalise_digest(cls, value: Any) -> str | None:
        return normalise_content_digest(value)

    # -- contract enforcement -------------------------------------------

    @model_validator(mode="after")
    def _enforce_blocking_error_contract(self) -> "DecideResponse":
        """Refuse to parse a verdict that contradicts its own blocking errors.

        Checks the headline verdict *and* every embedded copy of it, because
        a stale build could scrub one and not the other, and a caller that
        renders ``explanation.decision`` would then show a success state the
        headline never claimed.
        """
        if not self.field_errors:
            return self
        contradictions: list[str] = []
        if self.decision != _NON_TERMINAL_DECISION:
            contradictions.append(f"decision={self.decision!r}")
        embedded_explanation = (self.explanation or {}).get("decision")
        if isinstance(embedded_explanation, str) and embedded_explanation not in (
            _NON_TERMINAL_DECISION,
            "",
        ):
            contradictions.append(f"explanation.decision={embedded_explanation!r}")
        embedded_trace = (self.trace or {}).get("status")
        if isinstance(embedded_trace, str) and embedded_trace.lower() in ("eligible", "not_eligible", "sat", "unsat"):
            contradictions.append(f"trace.status={embedded_trace!r}")
        if contradictions:
            raise AethisContractViolation(
                "Response reports a terminal verdict beside blocking field_errors "
                f"({', '.join(contradictions)}; blocking fields: {sorted(self.field_errors)}). "
                "A conforming engine forces decision='undetermined' whenever field_errors is "
                "non-empty, and scrubs every embedded copy. Refusing to surface a verdict "
                "computed beside errors the caller did not knowingly send."
            )
        return self

    # -- blocking errors -------------------------------------------------

    @property
    def blocking_errors(self) -> dict[str, str]:
        """Blocking input errors keyed by field id — ``{}`` when there are none.

        Always a mapping, so ``if response.blocking_errors:`` is the whole
        check; no ``None`` handling, no chance of a truthy ``None``.
        """
        return dict(self.field_errors or {})

    @property
    def has_blocking_errors(self) -> bool:
        return bool(self.field_errors)

    @property
    def is_terminal(self) -> bool:
        """True only for a verdict that is safe to treat as final.

        ``next_question is None`` is **not** a completion signal: the engine
        suppresses the next question whenever blocking errors are present, so
        a blocked response looks exactly like a finished one on that field.
        """
        return not self.has_blocking_errors and self.decision in ("eligible", "not_eligible")

    def raise_for_blocking_errors(self) -> "DecideResponse":
        """Turn blocking input errors into an exception rather than a branch.

        For callers who would rather fail loudly than remember to test
        :attr:`has_blocking_errors` on every call path.

        Returns ``self`` when clean, so it chains::

            answers = client.decide(...).raise_for_blocking_errors()
        """
        if self.has_blocking_errors:
            details = "; ".join(f"{field}: {message}" for field, message in sorted(self.blocking_errors.items()))
            raise AethisFieldErrors(
                f"{len(self.blocking_errors)} blocking field error(s) — the decision is undetermined "
                f"and cannot be treated as a verdict ({details})",
                field_errors=self.blocking_errors,
            )
        return self

    # -- identity ---------------------------------------------------------

    @property
    def content_identity(self) -> ContentIdentity | None:
        return _content_identity(self.ruleset_id, self.ruleset_version, self.content_digest)

    @property
    def replay_identity(self) -> ReplayIdentity | None:
        """The complete replay identity, or ``None`` if any part is unresolved."""
        try:
            return self.require_replay_identity()
        except AethisReplayIdentityError:
            return None

    def require_replay_identity(self) -> ReplayIdentity:
        """The complete replay identity, raising when any part is unresolved.

        Use this before persisting a decision as an audit record: it is the
        difference between storing a reference that can be replayed and
        storing one that merely looks like it can.
        """
        missing = _missing_identity_parts(
            decision_id=self.decision_id,
            inputs_hash=self.inputs_hash,
            engine_version=self.engine_version,
            ruleset_id=self.ruleset_id,
            ruleset_version=self.ruleset_version,
            content_digest=self.content_digest,
        )
        if missing:
            raise AethisReplayIdentityError(
                f"This decision has no complete replay identity: {', '.join(missing)} "
                f"{'is' if len(missing) == 1 else 'are'} unresolved. A published leaf ruleset "
                "always resolves all of them; rulebook decisions do not yet resolve composed "
                "identity. Do not persist this decision as a replayable audit record.",
                missing=missing,
            )
        assert self.decision_id and self.inputs_hash and self.engine_version  # narrowed by `missing`
        assert self.ruleset_id and self.ruleset_version and self.content_digest
        return ReplayIdentity(
            decision_id=self.decision_id,
            inputs_hash=self.inputs_hash,
            engine_version=self.engine_version,
            ruleset_id=self.ruleset_id,
            ruleset_version=self.ruleset_version,
            content_digest=self.content_digest,
        )

    # -- explanation -------------------------------------------------------

    @property
    def decision_explanation(self) -> DecisionExplanation | None:
        """The typed explanation, or ``None`` when none was requested.

        ``explanation`` stays the raw wire dict for back-compatibility; this
        accessor parses it into :class:`DecisionExplanation`, including typed
        :class:`SourceReference` objects on each criterion.
        """
        if self.explanation is None:
            return None
        return DecisionExplanation.model_validate(self.explanation)

    def source_references(self) -> dict[str, list[SourceReference]]:
        """Typed source references from this decision's explanation, keyed by
        ``criterion_id``. Empty when the call did not request an explanation
        or the ruleset carries no published references."""
        explanation = self.decision_explanation
        return explanation.source_references() if explanation is not None else {}


class SchemaField(BaseModel):
    """A single field definition from a ruleset schema.

    ``enum_labels`` and ``canonical_field`` are authored metadata the engine
    carries but never interprets (aethis-core#449). Both are ``None`` against
    an engine predating them and against a field whose author declared
    neither — the two are indistinguishable here, so treat ``None`` as "render
    the slug", never as "the engine is old".
    """

    field_id: str
    field_type: str
    description: str | None = None
    question: str | None = None
    enum_values: list[str] | None = None
    enum_labels: dict[str, str] | None = None
    canonical_field: str | None = None


class SchemaResponse(BaseModel):
    """Response body from ``GET /api/v1/public/rulesets/{id}/schema``.

    Carries the same resolved immutable identity as ``/decide`` and
    ``/explain``: a schema fetched for a slug reports the ``ruleset_id``,
    ``ruleset_version`` and ``content_digest`` of the content it actually
    describes, so answers collected against it can be bound to that content.
    Unresolved values normalise to ``None`` — never ``"unknown"``.
    """

    ruleset_id: str
    slug: str | None = None
    name: str | None = None
    fields: list[SchemaField]
    ruleset_version: str | None = None
    content_digest: str | None = None
    engine_version: str | None = None

    @field_validator("ruleset_version", mode="before")
    @classmethod
    def _normalise(cls, value: Any) -> str | None:
        return normalise_identity_value(value)

    @field_validator("content_digest", mode="before")
    @classmethod
    def _normalise_digest(cls, value: Any) -> str | None:
        return normalise_content_digest(value)

    @property
    def content_identity(self) -> ContentIdentity | None:
        return _content_identity(self.ruleset_id, self.ruleset_version, self.content_digest)

    def require_content_identity(self) -> ContentIdentity:
        return _require_content_identity(self.ruleset_id, self.ruleset_version, self.content_digest, "schema")


class RulebookSchemaResponse(BaseModel):
    """Response body from ``GET /api/v1/public/rulebooks/{id}/schema``.

    The rulebook analogue of :class:`SchemaResponse`: the combined field
    schema across every ruleset the rulebook composes, plus two fields the
    single-ruleset schema doesn't carry: ``robot_hints`` (natural-language
    conversational-agent guidance authored on the rulebook, keyed by beat —
    ``general_context``, ``preamble``, ``session_start``, ``postamble``,
    ``session_end``, ``stuck``) and ``engine_version`` (the engine build that
    resolved the schema). Both are ``None`` for a rulebook authored before
    these fields existed — additive and back-compat.
    """

    rulebook_id: str
    sections: list[str] = Field(default_factory=list)
    fields: list[SchemaField] = Field(default_factory=list)
    robot_hints: dict[str, str] | None = None
    engine_version: str | None = None


class RulesetGraph(BaseModel):
    """The JSON graph IR returned inside a graph response: nodes/edges plus
    summary stats.

    Node shape varies by ``type`` (``field`` / ``criterion`` / ``group`` /
    ``outcome`` — each carries different keys, e.g. only ``criterion`` nodes
    carry ``display``), so nodes and edges are kept as loosely-typed dicts
    rather than a rigid per-type model. This is deliberate: it lets a legacy
    or empty graph (``nodes: []``) parse cleanly instead of failing closed the
    moment the engine adds a new node type or field.
    """

    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    stats: dict[str, Any] | None = None


class GraphResponse(BaseModel):
    """Response body from ``GET /api/v1/public/rulesets/{id}/graph`` or
    ``GET /api/v1/public/rulebooks/{id}/graph``.

    The field -> criterion -> group -> outcome dependency graph, plus a
    rendered Mermaid diagram. Carries either ``ruleset_id`` (single-ruleset
    graph) or ``rulebook_id`` (rulebook-composed graph) — mirrors the same
    split on :class:`DecideResponse`. ``graph``/``mermaid`` are each optional
    because the engine's ``?format=`` query param can return graph-only or
    mermaid-only.
    """

    ruleset_id: str | None = None
    rulebook_id: str | None = None
    slug: str | None = None
    name: str | None = None
    graph: RulesetGraph | None = None
    mermaid: str | None = None


class RulesetSummary(BaseModel):
    """One item from ``GET /api/v1/public/rulesets`` (anonymous catalogue).

    ``name`` is the human-readable section name surfaced by aethis-core
    v0.18.0 onward. Historical rulesets published before the backfill
    serialise with ``name=None``.
    """

    ruleset_id: str
    slug: str | None = None
    section_id: str
    name: str | None = None
    description: str
    field_count: int
    rule_count: int


class RulesetListItem(BaseModel):
    """One item from ``GET /api/v1/public/projects/{id}/rulesets``.

    Project-scoped listing — requires an API key. ``name`` mirrors the
    field added to ``RulesetSummary`` in aethis-core v0.18.0; pre-backfill
    rulesets serialise with ``name=None``.
    """

    ruleset_id: str
    section_id: str
    name: str | None = None
    status: str
    version: str
    label: str | None = None
    total_fields: int
    total_rules: int
    created_at: str | None = None


class ClassUsage(BaseModel):
    """Per-operation-class budget for the calling key (epic aethis-workspace#552)."""

    model_config = ConfigDict(populate_by_name=True)

    operation_class: str = Field(alias="class")
    limit: int
    used: int
    remaining: int
    reset: int  # epoch seconds of the next reset (rolling-window hour boundary)


class RollingUsage(BaseModel):
    last_7_days: dict[str, int] = Field(default_factory=dict)
    last_30_days: dict[str, int] = Field(default_factory=dict)


class UsageResponse(BaseModel):
    """The `GET /api/v1/public/usage` payload: per-class budget + rolling summary."""

    tier: str
    classes: list[ClassUsage]
    rolling: RollingUsage


class RateLimit(BaseModel):
    """The `X-RateLimit-*` budget parsed from the most recent response (epic #552).

    Exposed via ``client.rate_limit`` so a consuming app can read remaining budget
    (especially ``generate``) without a separate ``usage()`` call. None until the
    first metered, authenticated response."""

    operation_class: str  # X-RateLimit-Class
    limit: int
    remaining: int
    reset: int  # epoch seconds


__all__ = [
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
]
