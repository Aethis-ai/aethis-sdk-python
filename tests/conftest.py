"""Shared test fixtures and helpers."""

from __future__ import annotations

from typing import Any

import httpx


def make_decide_response(**overrides: Any) -> dict[str, Any]:
    """Build a valid /decide JSON body with sensible defaults."""
    base: dict[str, Any] = {
        "decision": "undetermined",
        "ruleset_id": "test_ruleset:v1",
        "ruleset_version": "v1",
        "engine_version": "aethis-core@0.10.0",
        "decision_id": "dec_TestFixtureId000001",
        "inputs_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        "decision_time": "2026-05-06T12:00:00Z",
        "fields_evaluated": 3,
        "fields_provided": 1,
        "missing_fields": ["age", "residency"],
        "next_question": {"field_id": "age", "question": "How old are you?", "weight": 1},
        "optimal_path": None,
        "field_errors": None,
        "trace": None,
        "explanation": None,
        "section_results": None,
    }
    base.update(overrides)
    return base


def make_schema_response(**overrides: Any) -> dict[str, Any]:
    """Build a valid /schema JSON body."""
    base: dict[str, Any] = {
        "ruleset_id": "test_ruleset:v1",
        "fields": [
            {
                "field_id": "age",
                "field_type": "integer",
                "description": "Age of applicant",
                "question": "How old are you?",
                "enum_values": None,
            },
            {
                "field_id": "has_passport",
                "field_type": "boolean",
                "description": "Has valid passport",
                "question": "Do you have a valid passport?",
                "enum_values": None,
            },
            {
                "field_id": "degree_origin",
                "field_type": "enum",
                "description": "Where the degree was awarded",
                "question": "Where was your degree awarded?",
                "enum_values": ["uk", "non_uk"],
            },
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
