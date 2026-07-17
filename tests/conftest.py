"""Shared test fixtures and helpers."""

from __future__ import annotations

from typing import Any

import httpx


def make_next_question(**overrides: Any) -> dict[str, Any]:
    """One /decide ``next_question`` object, mirroring the deployed engine shape
    (``sort`` / ``enum_values`` / ``x_ui_widget`` / ``notes`` included for parity)."""
    base: dict[str, Any] = {
        "field_id": "age",
        "question": "How old are you?",
        "weight": 1,
        "sort": None,
        "enum_values": None,
        "x_ui_widget": None,
        "notes": [],
    }
    base.update(overrides)
    return base


def make_decide_response(**overrides: Any) -> dict[str, Any]:
    """Build a valid /decide JSON body with sensible defaults."""
    base: dict[str, Any] = {
        "decision": "undetermined",
        "ruleset_id": "test_ruleset:v1",
        "rulebook_id": None,
        "slug": None,
        "ruleset_version": "v1",
        "engine_version": "aethis-core@0.10.0",
        "decision_id": "dec_TestFixtureId000001",
        "inputs_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "decision_time": "2026-05-06T12:00:00Z",
        "fields_evaluated": 3,
        "fields_provided": 1,
        "missing_fields": ["age", "residency"],
        "next_question": make_next_question(),
        "optimal_path": None,
        "field_errors": None,
        "trace": None,
        "explanation": None,
        "section_results": None,
        # Keys the deployed engine also returns on /decide; kept here so the
        # recorded-live parity check (tests/integration/test_fixture_parity.py)
        # sees the fixture as a superset of reality rather than stale.
        "graph_overlay": None,
        "timing": None,
    }
    base.update(overrides)
    return base


def _schema_field(
    field_id: str,
    field_type: str,
    description: str,
    question: str,
    enum_values: list[str] | None = None,
) -> dict[str, Any]:
    """One /schema field entry, mirroring the deployed engine's field shape
    (``notes`` / ``weight`` / ``x_ui_widget`` included for parity)."""
    return {
        "field_id": field_id,
        "field_type": field_type,
        "description": description,
        "question": question,
        "enum_values": enum_values,
        "notes": [],
        "weight": 1,
        "x_ui_widget": None,
    }


def make_schema_response(**overrides: Any) -> dict[str, Any]:
    """Build a valid /schema JSON body."""
    base: dict[str, Any] = {
        "ruleset_id": "test_ruleset:v1",
        # ``name`` / ``slug`` are returned by the deployed engine's /schema;
        # carried here so the parity check sees a superset of reality.
        "name": "Test Ruleset",
        "slug": "aethis/test-ruleset",
        "fields": [
            _schema_field("age", "integer", "Age of applicant", "How old are you?"),
            _schema_field("has_passport", "boolean", "Has valid passport", "Do you have a valid passport?"),
            _schema_field(
                "degree_origin",
                "enum",
                "Where the degree was awarded",
                "Where was your degree awarded?",
                enum_values=["uk", "non_uk"],
            ),
        ],
    }
    base.update(overrides)
    return base


def make_ruleset_summary(**overrides: Any) -> dict[str, Any]:
    """Build one valid item from the ``GET /rulesets`` catalogue response."""
    base: dict[str, Any] = {
        "ruleset_id": "construction-all-risks:20260517-a7234924",
        "slug": "aethis/construction-all-risks",
        "section_id": "construction-all-risks",
        "name": "Construction All Risks",
        "description": "Generated via agent authoring",
        "field_count": 14,
        "rule_count": 8,
    }
    base.update(overrides)
    return base


def sync_mock_transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def async_mock_transport(handler: Any) -> httpx.MockTransport:
    return httpx.MockTransport(handler)
