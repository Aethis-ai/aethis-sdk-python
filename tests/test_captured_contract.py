"""The captured engine payloads are the contract this SDK is tested against.

Every fixture under ``tests/fixtures/`` was recorded from a live engine by
``scripts/capture_engine_fixtures.py`` (see each file's ``provenance`` block) —
no hand-written approximations. These tests hold two lines:

1. each captured body still validates against the engine's **own** JSON Schema,
   captured from the same ``/openapi.json`` in the same run; and
2. the SDK's models parse those bodies losslessly enough to answer the
   questions callers ask of them.

The second line is why the first matters. A fixture that drifts from the wire
turns the whole mocked suite into a test of a shape that no longer exists.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from aethis_sdk import DecideResponse, ExplainResponse, SchemaResponse
from tests.conftest import engine_schema, engine_schema_registry, load_fixture, wire_body, wire_record


def validate_against_engine_schema(instance: Any, schema_name: str) -> None:
    """Validate ``instance`` against a component schema captured from the engine.

    The registry is spliced in under ``components/schemas`` so the captured
    ``$ref``s (``#/components/schemas/SourceReference``) resolve inside the
    same document.
    """
    schema = dict(engine_schema(schema_name))
    schema["components"] = {"schemas": engine_schema_registry()}
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: list(e.path))
    assert not errors, "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:10])


WIRE_CASES = [
    ("decide_partial", "DecideResponse"),
    ("decide_blocking_field_errors", "DecideResponse"),
    ("decide_with_explanation", "DecideResponse"),
    ("explain", "ExplainRulesetResponse"),
]


class TestCapturedFixturesMatchTheEngineSchema:
    @pytest.mark.parametrize("fixture_name,schema_name", WIRE_CASES)
    def test_body_validates(self, fixture_name: str, schema_name: str) -> None:
        validate_against_engine_schema(wire_body(fixture_name), schema_name)

    def test_every_wire_fixture_records_its_provenance(self) -> None:
        for name in (
            "decide_partial",
            "decide_blocking_field_errors",
            "decide_with_explanation",
            "decide_unknown_key_422",
            "explain",
            "schema",
            "unauthenticated_401",
        ):
            provenance = wire_record(name)["provenance"]
            assert provenance["captured_from"].startswith("https://")
            assert provenance["engine_version"]
            assert provenance["anonymous"] is True, "fixtures must never be captured with a credential"

    def test_openapi_subset_pins_the_engine_build_it_came_from(self) -> None:
        provenance = load_fixture("engine_openapi_subset")["provenance"]
        assert provenance["captured_from"].endswith("/openapi.json")
        assert provenance["engine_version"]


class TestModelsParseTheCapturedBodies:
    def test_decide_partial(self) -> None:
        response = DecideResponse.model_validate(wire_body("decide_partial"))
        assert response.decision == "undetermined"
        assert not response.has_blocking_errors
        assert response.next_question is not None
        # A published leaf always resolves all three identity parts.
        identity = response.require_replay_identity()
        assert identity.ruleset_version and identity.content_digest.startswith("sha256:")
        # ...and the engine returns the immutable id, never the caller's slug.
        assert identity.ruleset_id != wire_record("decide_partial")["request"]["body"]["ruleset_id"]

    def test_decide_blocking(self) -> None:
        response = DecideResponse.model_validate(wire_body("decide_blocking_field_errors"))
        assert response.has_blocking_errors
        assert response.decision == "undetermined"
        assert response.next_question is None, "the captured payload is the trap this SDK guards against"
        assert response.is_terminal is False

    def test_schema_carries_resolved_identity(self) -> None:
        response = SchemaResponse.model_validate(wire_body("schema"))
        identity = response.require_content_identity()
        assert identity.ruleset_version
        assert identity.content_digest.startswith("sha256:")
        assert response.fields, "captured schema had no fields"

    def test_explain_carries_resolved_identity(self) -> None:
        response = ExplainResponse.model_validate(wire_body("explain"))
        identity = response.require_content_identity()
        assert identity.ruleset_id == response.ruleset_id
        assert response.criteria and response.criteria[0].rule_text


class TestTheTwoExplanationShapesAreDifferent:
    """A single fixture serving the flat shape on both paths would test neither.

    ``GET /explain`` returns a flat ``criteria`` array; ``POST /decide`` nests
    criteria under ``explanation.groups[].criteria[]``. Both captures are real,
    and these assertions fail if either fixture is ever replaced by the other's
    shape.
    """

    def test_explain_is_flat(self) -> None:
        body = wire_body("explain")
        assert isinstance(body["criteria"], list)
        assert "groups" not in body
        assert "rule_text" in body["criteria"][0]

    def test_decide_explanation_is_nested(self) -> None:
        explanation = wire_body("decide_with_explanation")["explanation"]
        assert "groups" in explanation
        assert "criteria" not in explanation, "decide must NOT expose a flat criteria array"
        assert explanation["groups"][0]["criteria"][0]["criterion_id"]

    def test_the_sdk_models_the_two_shapes_separately(self) -> None:
        decide = DecideResponse.model_validate(wire_body("decide_with_explanation"))
        explanation = decide.decision_explanation
        assert explanation is not None
        assert explanation.groups, "nested groups did not survive typing"

        explain = ExplainResponse.model_validate(wire_body("explain"))
        assert explain.criteria, "flat criteria did not survive typing"

        # The nested shape must not parse as the flat one, or the fixture swap
        # this test exists to catch would go unnoticed.
        flat_as_decide = DecideResponse.model_validate(
            {**wire_body("decide_partial"), "explanation": wire_body("explain")}
        )
        assert flat_as_decide.decision_explanation is not None
        assert flat_as_decide.decision_explanation.groups == []


class TestRequestSurface:
    def test_unknown_top_level_keys_are_rejected_by_the_engine(self) -> None:
        record = wire_record("decide_unknown_key_422")
        assert record["status"] == 422
        assert "batch" in record["request"]["body"]
        assert any(entry["type"] == "extra_forbidden" for entry in record["body"]["detail"])

    def test_decide_request_schema_forbids_extra_properties(self) -> None:
        assert engine_schema("DecideRequest").get("additionalProperties") is False

    def test_the_sdk_sends_only_contract_keys(self) -> None:
        from aethis_sdk.client import _decide_payload, _decide_rulebook_payload

        allowed = set(engine_schema("DecideRequest")["properties"])
        for payload in (
            _decide_payload("r", {}, False, False, False),
            _decide_rulebook_payload("rb", {}, False, False, False),
        ):
            unknown = set(payload) - allowed
            assert not unknown, f"SDK would send keys the engine rejects with 422: {sorted(unknown)}"


class TestFixturesAreCommittedAsCapturedJson:
    def test_fixtures_are_readable_json(self) -> None:
        for name in ("engine_openapi_subset", "source_reference_exemplar"):
            assert isinstance(json.dumps(load_fixture(name)), str)
