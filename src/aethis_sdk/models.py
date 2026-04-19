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
    """Per-section result for multi-section bundles."""

    section_id: str
    bundle_id: str | None = None
    status: SectionStatus


class DecideResponse(BaseModel):
    """Response body from ``POST /api/v1/public/decide``."""

    decision: Decision
    bundle_id: str | None = None
    ruleset_id: str | None = None
    bundle_version: str = "unknown"
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
    """A single field definition from a bundle schema."""

    field_id: str
    field_type: str
    description: str | None = None
    question: str | None = None
    enum_values: list[str] | None = None


class SchemaResponse(BaseModel):
    """Response body from ``GET /api/v1/public/bundles/{id}/schema``."""

    bundle_id: str
    fields: list[SchemaField]
