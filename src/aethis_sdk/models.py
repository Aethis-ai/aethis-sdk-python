"""Pydantic response models for the Aethis public API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

Decision = Literal["eligible", "not_eligible", "undetermined"]
SectionStatus = Literal["satisfied", "not_satisfied", "pending"]


class NextQuestion(BaseModel):
    """The next field the API recommends asking about."""

    field_id: str
    question: str
    weight: int


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
    explanation: list[dict[str, Any]] | None = None
    section_results: list[SectionResult] | None = None


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
