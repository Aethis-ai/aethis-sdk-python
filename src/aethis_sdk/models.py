"""Pydantic response models for the Aethis public API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Decision = Literal["eligible", "not_eligible", "undetermined"]
SectionStatus = Literal["satisfied", "not_satisfied", "pending"]


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


class DecideResponse(BaseModel):
    """Response body from ``POST /api/v1/public/decide``.

    Carries either ``ruleset_id`` (single-ruleset decide) or ``rulebook_id``
    (composed multi-ruleset rulebook decide). ``slug`` echoes whichever
    identifier was used as a slug — opaque ``rb_*`` ids leave it ``None``.
    """

    decision: Decision
    ruleset_id: str | None = None
    rulebook_id: str | None = None
    slug: str | None = None
    ruleset_version: str = "unknown"
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


class SchemaField(BaseModel):
    """A single field definition from a ruleset schema."""

    field_id: str
    field_type: str
    description: str | None = None
    question: str | None = None
    enum_values: list[str] | None = None


class SchemaResponse(BaseModel):
    """Response body from ``GET /api/v1/public/rulesets/{id}/schema``."""

    ruleset_id: str
    slug: str | None = None
    name: str | None = None
    fields: list[SchemaField]
    engine_version: str | None = None


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
