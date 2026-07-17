"""Model-level tests — Pydantic schema for /decide and /schema responses."""

from __future__ import annotations

from aethis_sdk import (
    DecideResponse,
    FieldNote,
    GraphResponse,
    RulebookSchemaResponse,
    RulesetGraph,
    RulesetListItem,
    RulesetSummary,
    SchemaResponse,
)


class TestDecideResponseAuditFields:
    """Audit-trail fields on /decide must round-trip from the API JSON.

    Regression: prior to 0.3.2, ``DecideResponse`` did not declare
    ``decision_id``, ``inputs_hash``, ``decision_time``, or
    ``engine_version`` — Pydantic silently dropped them, leaving SDK
    callers unable to read the audit fingerprint that the homepage and
    docs prominently advertise.
    """

    def test_audit_fields_round_trip(self):
        payload = {
            "decision": "eligible",
            "slug": "aethis/uk-fsm/child-eligibility",
            "engine_version": "aethis-core@0.10.0",
            "fields_evaluated": 2,
            "fields_provided": 2,
            "decision_id": "dec_GjBMU4o8sNvNRmaR",
            "inputs_hash": "sha256:75c958f1a3d72335ccf67c7d5e32f58b57966e0873786843c353b09f787c5ec2",
            "decision_time": "2026-04-26T23:20:41Z",
        }

        resp = DecideResponse.model_validate(payload)

        assert resp.decision == "eligible"
        assert resp.engine_version == "aethis-core@0.10.0"
        assert resp.decision_id == "dec_GjBMU4o8sNvNRmaR"
        assert resp.inputs_hash == "sha256:75c958f1a3d72335ccf67c7d5e32f58b57966e0873786843c353b09f787c5ec2"
        assert resp.decision_time == "2026-04-26T23:20:41Z"

    def test_audit_fields_optional_for_back_compat(self):
        """Older engines that omit the audit fields must still parse."""
        resp = DecideResponse.model_validate({"decision": "undetermined"})

        assert resp.decision == "undetermined"
        assert resp.decision_id is None
        assert resp.inputs_hash is None
        assert resp.decision_time is None
        assert resp.engine_version is None

    def test_ruleset_id_is_settable_once(self):
        """Regression: prior to 0.3.2, ``ruleset_id`` was declared twice on
        ``DecideResponse``; Pydantic silently overrode the first with the
        second. After the dedupe, a single declaration accepts the value."""
        resp = DecideResponse.model_validate({"decision": "eligible", "ruleset_id": "test:v1"})
        assert resp.ruleset_id == "test:v1"


class TestNextQuestionNotes:
    """``NextQuestion.notes`` carries the engine's structured ``FieldNoteOut``
    guidance; it must round-trip and stay optional for responses without it.
    """

    def test_notes_parse_onto_next_question(self):
        payload = {
            "decision": "undetermined",
            "next_question": {
                "field_id": "life_uk.passed",
                "question": "Have you passed the Life in the UK test?",
                "weight": 3,
                "notes": [
                    {
                        "note_text": "Required unless exempt on grounds of age or long residence.",
                        "source": "Nationality: naturalisation (Home Office guidance)",
                        "metadata": {"type": "why", "section": "life_uk"},
                    }
                ],
            },
        }
        resp = DecideResponse.model_validate(payload)

        assert resp.next_question is not None
        assert len(resp.next_question.notes) == 1
        note = resp.next_question.notes[0]
        assert isinstance(note, FieldNote)
        assert note.note_text.startswith("Required unless exempt")
        assert note.source.startswith("Nationality")
        assert note.metadata["type"] == "why"

    def test_notes_default_empty_when_absent(self):
        """Responses from engines/paths that omit notes keep parsing."""
        resp = DecideResponse.model_validate(
            {
                "decision": "undetermined",
                "next_question": {"field_id": "age", "question": "How old?", "weight": 1},
            }
        )
        assert resp.next_question is not None
        assert resp.next_question.notes == []

    def test_field_note_source_and_metadata_default(self):
        note = FieldNote.model_validate({"note_text": "Bare note."})
        assert note.source == ""
        assert note.metadata == {}


class TestDecideResponseExplanation:
    """``explanation`` is a single object (``dict``), not a list — matching the
    engine's ``Optional[Dict[str, Any]]``."""

    def test_explanation_object_round_trips(self):
        explanation = {
            "decision": "eligible",
            "groups": [{"group": "age", "status": "satisfied", "criteria": []}],
            "unused_facts": [],
        }
        resp = DecideResponse.model_validate({"decision": "eligible", "explanation": explanation})
        assert resp.explanation == explanation
        assert resp.explanation["decision"] == "eligible"

    def test_explanation_optional(self):
        resp = DecideResponse.model_validate({"decision": "undetermined"})
        assert resp.explanation is None


class TestRulesetNameField:
    """The ``name`` field added in aethis-core v0.18.0 must round-trip
    through the SDK's typed listing models, and remain optional so that
    pre-backfill rulesets (which serialise ``name=None``) keep parsing.
    """

    def test_ruleset_summary_has_name_field(self):
        assert "name" in RulesetSummary.model_fields

    def test_ruleset_list_item_has_name_field(self):
        assert "name" in RulesetListItem.model_fields

    def test_schema_response_has_name_field(self):
        assert "name" in SchemaResponse.model_fields

    def test_ruleset_summary_round_trip_with_name(self):
        payload = {
            "ruleset_id": "construction-all-risks:20260517-a7234924",
            "slug": "aethis/construction-all-risks",
            "section_id": "construction-all-risks",
            "name": "Construction All Risks",
            "description": "Generated via agent authoring",
            "field_count": 14,
            "rule_count": 8,
        }
        item = RulesetSummary.model_validate(payload)
        assert item.name == "Construction All Risks"
        assert item.slug == "aethis/construction-all-risks"

    def test_ruleset_summary_name_optional_for_pre_backfill(self):
        """Historical rulesets published before the v0.18.0 backfill
        return ``name=None`` and must still parse."""
        payload = {
            "ruleset_id": "legacy:20260101-deadbeef",
            "slug": "aethis/legacy",
            "section_id": "legacy",
            "description": "Pre-backfill ruleset",
            "field_count": 3,
            "rule_count": 2,
        }
        item = RulesetSummary.model_validate(payload)
        assert item.name is None

    def test_ruleset_list_item_round_trip_with_name(self):
        payload = {
            "ruleset_id": "myproj-criteria:20260518-abc123",
            "section_id": "myproj-criteria",
            "name": "MyProj Eligibility Criteria",
            "status": "active",
            "version": "1.0.0",
            "label": None,
            "total_fields": 5,
            "total_rules": 3,
            "created_at": "2026-05-18T10:00:00Z",
        }
        item = RulesetListItem.model_validate(payload)
        assert item.name == "MyProj Eligibility Criteria"
        assert item.status == "active"

    def test_schema_response_round_trip_with_name(self):
        payload = {
            "ruleset_id": "construction-all-risks:20260517-a7234924",
            "slug": "aethis/construction-all-risks",
            "name": "Construction All Risks",
            "fields": [
                {"field_id": "site_address", "field_type": "string"},
            ],
        }
        resp = SchemaResponse.model_validate(payload)
        assert resp.name == "Construction All Risks"
        assert resp.fields[0].field_id == "site_address"


class TestSchemaResponseEngineVersion:
    """``engine_version`` added to the ruleset schema response — additive,
    default ``None`` for the live route (which doesn't send it today)."""

    def test_engine_version_optional_for_back_compat(self):
        payload = {
            "ruleset_id": "construction-all-risks:20260412-gold",
            "slug": None,
            "name": "CAR_DEFECT_EXCLUSION",
            "fields": [],
        }
        resp = SchemaResponse.model_validate(payload)
        assert resp.engine_version is None

    def test_engine_version_round_trips_when_present(self):
        payload = {
            "ruleset_id": "x:v1",
            "fields": [],
            "engine_version": "aethis-core@0.45.2",
        }
        resp = SchemaResponse.model_validate(payload)
        assert resp.engine_version == "aethis-core@0.45.2"


class TestRulebookSchemaResponse:
    """``RulebookSchemaResponse`` — ``robot_hints`` + ``engine_version`` on the
    rulebook ``/schema`` route.

    The "with robot hints" payload below is a live response captured
    directly from ``staging.api.aethis.ai`` (aethis-core@0.45.2) for a
    throwaway rulebook created and archived during this issue's
    verification, ``GET /api/v1/public/rulebooks/{id}/schema``:

        {"rulebook_id": "rb_SxYaJv5uSvb5qHzW", "sections": [], "fields": [],
         "robot_hints": {"general_context": "..."},
         "engine_version": "aethis-core@0.45.2"}
    """

    def test_round_trips_robot_hints_and_engine_version(self):
        payload = {
            "rulebook_id": "rb_SxYaJv5uSvb5qHzW",
            "sections": [],
            "fields": [],
            "robot_hints": {"general_context": "This is a smoke-test rulebook for SDK model round-trip testing."},
            "engine_version": "aethis-core@0.45.2",
        }
        resp = RulebookSchemaResponse.model_validate(payload)
        assert resp.rulebook_id == "rb_SxYaJv5uSvb5qHzW"
        assert resp.robot_hints == {
            "general_context": "This is a smoke-test rulebook for SDK model round-trip testing."
        }
        assert resp.engine_version == "aethis-core@0.45.2"

    def test_legacy_rulebook_schema_without_robot_hints_still_parses(self):
        """A rulebook authored before robot_hints/engine_version existed
        returns null for both — the schema route must not fail closed."""
        payload = {
            "rulebook_id": "rb_legacy",
            "sections": ["life_uk"],
            "fields": [
                {"field_id": "life_uk.passed", "field_type": "boolean"},
            ],
        }
        resp = RulebookSchemaResponse.model_validate(payload)
        assert resp.robot_hints is None
        assert resp.engine_version is None
        assert resp.fields[0].field_id == "life_uk.passed"

    def test_fields_and_sections_default_empty(self):
        resp = RulebookSchemaResponse.model_validate({"rulebook_id": "rb_x"})
        assert resp.sections == []
        assert resp.fields == []


class TestGraphResponse:
    """``GraphResponse`` / ``RulesetGraph`` for the new ``/graph`` endpoint.

    The payload below is a **trimmed, structurally-faithful excerpt** of a
    live response captured from
    ``GET https://api.aethis.ai/api/v1/public/rulesets/construction-all-risks:20260412-gold/graph``
    (aethis-core@0.45.2, public/no-auth) — one representative node of each
    ``type`` (``field`` / ``criterion`` / ``group`` / ``outcome``), the first
    two real edges, and the real ``stats`` block. The full live response has
    37 nodes; trimmed here for test readability without altering any shape.
    """

    def test_round_trips_live_ruleset_graph_shape(self):
        payload = {
            "ruleset_id": "construction-all-risks:20260412-gold",
            "slug": None,
            "name": "CAR_DEFECT_EXCLUSION",
            "graph": {
                "nodes": [
                    {
                        "id": "field:car.policy.period_valid",
                        "type": "field",
                        "label": "car.policy.period_valid",
                        "sort": "Bool",
                        "description": "Did the loss occur within the policy period?",
                        "enum_values": None,
                        "sections": ["construction-all-risks:20260412-gold"],
                        "shared": False,
                    },
                    {
                        "id": "criterion:period_valid",
                        "type": "criterion",
                        "label": "Policy period check (Cl.3)",
                        "title": "Policy period check (Cl.3)",
                        "section_id": "construction-all-risks:20260412-gold",
                        "group": "policy_period",
                        "fields": ["car.policy.period_valid"],
                        "display": {
                            "sentence": "car.policy.period_valid equals true",
                            "routes": {
                                "id": "r",
                                "kind": "leaf",
                                "label": "car.policy.period_valid equals true",
                                "expr": {
                                    "type": "op",
                                    "operator": "=",
                                    "args": [
                                        {"type": "field_ref", "key": "car.policy.period_valid"},
                                        {"type": "const", "sort": "Bool", "value": True, "field_context": None},
                                    ],
                                },
                                "overlay": None,
                            },
                            "expr": {
                                "type": "op",
                                "operator": "=",
                                "args": [
                                    {"type": "field_ref", "key": "car.policy.period_valid"},
                                    {"type": "const", "sort": "Bool", "value": True, "field_context": None},
                                ],
                            },
                        },
                        "overlay": None,
                    },
                    {
                        "id": "group:construction-all-risks:20260412-gold.policy_period",
                        "type": "group",
                        "label": "policy_period",
                        "section_id": "construction-all-risks:20260412-gold",
                        "scoped_name": "construction-all-risks:20260412-gold.policy_period",
                        "criteria": ["period_valid"],
                        "semantics": "single",
                    },
                    {
                        "id": "outcome",
                        "type": "outcome",
                        "label": "Eligibility Outcome",
                        "has_custom_logic": False,
                    },
                ],
                "edges": [
                    {
                        "source": "field:car.policy.period_valid",
                        "target": "criterion:period_valid",
                        "type": "field_to_criterion",
                        "section_id": "construction-all-risks:20260412-gold",
                    },
                    {
                        "source": "criterion:period_valid",
                        "target": "group:construction-all-risks:20260412-gold.policy_period",
                        "type": "criterion_to_group",
                        "section_id": "construction-all-risks:20260412-gold",
                    },
                ],
                "sections": ["construction-all-risks:20260412-gold"],
                "stats": {
                    "total_fields": 11,
                    "shared_fields": 0,
                    "total_criteria": 13,
                    "total_groups": 12,
                    "sections": 1,
                },
            },
            "mermaid": "graph TD\n  subgraph construction-all-risks:20260412-gold[...]",
        }

        resp = GraphResponse.model_validate(payload)
        assert isinstance(resp, GraphResponse)
        assert resp.ruleset_id == "construction-all-risks:20260412-gold"
        assert resp.rulebook_id is None
        assert isinstance(resp.graph, RulesetGraph)
        assert len(resp.graph.nodes) == 4
        node_types = {n["type"] for n in resp.graph.nodes}
        assert node_types == {"field", "criterion", "group", "outcome"}
        # A criterion node's nested display/routes/expr survive untouched.
        criterion = next(n for n in resp.graph.nodes if n["type"] == "criterion")
        assert criterion["display"]["sentence"] == "car.policy.period_valid equals true"
        assert criterion["display"]["routes"]["kind"] == "leaf"
        assert resp.graph.stats == {
            "total_fields": 11,
            "shared_fields": 0,
            "total_criteria": 13,
            "total_groups": 12,
            "sections": 1,
        }
        assert resp.mermaid is not None and resp.mermaid.startswith("graph TD")

    def test_rulebook_graph_carries_rulebook_id_not_ruleset_id(self):
        """The rulebook graph route (``GET .../rulebooks/{id}/graph``) omits
        ``ruleset_id``/``slug``/``name`` and returns ``rulebook_id`` instead —
        confirmed against aethis-core's ``get_rulebook_graph`` handler, which
        seeds its result dict with only ``{"rulebook_id": rulebook_id}``."""
        payload = {
            "rulebook_id": "rb_SxYaJv5uSvb5qHzW",
            "graph": {"nodes": [], "edges": [], "sections": [], "stats": {}},
            "mermaid": "graph TD\n",
        }
        resp = GraphResponse.model_validate(payload)
        assert resp.rulebook_id == "rb_SxYaJv5uSvb5qHzW"
        assert resp.ruleset_id is None
        assert resp.graph.nodes == []

    def test_legacy_or_empty_graph_still_parses(self):
        """A ruleset with no criteria (or a legacy graph shape predating a
        node type) must not fail closed — nodes/edges default to empty."""
        payload = {
            "ruleset_id": "empty:v1",
            "graph": {"nodes": [], "edges": [], "sections": [], "stats": None},
        }
        resp = GraphResponse.model_validate(payload)
        assert resp.graph.nodes == []
        assert resp.graph.stats is None
        assert resp.mermaid is None

    def test_graph_and_mermaid_are_independently_optional(self):
        """``?format=mermaid`` omits ``graph`` entirely; ``?format=graph``
        omits ``mermaid`` entirely — both must parse."""
        mermaid_only = GraphResponse.model_validate({"ruleset_id": "x:v1", "mermaid": "graph TD\n"})
        assert mermaid_only.graph is None
        assert mermaid_only.mermaid == "graph TD\n"

        graph_only = GraphResponse.model_validate(
            {"ruleset_id": "x:v1", "graph": {"nodes": [], "edges": [], "sections": [], "stats": None}}
        )
        assert graph_only.mermaid is None
        assert graph_only.graph is not None


class TestDecideResponseGraphOverlay:
    """``graph_overlay`` — the ``/decide`` counterpart of ``include_graph_overlay``."""

    def test_graph_overlay_optional_for_back_compat(self):
        resp = DecideResponse.model_validate({"decision": "eligible"})
        assert resp.graph_overlay is None

    def test_graph_overlay_round_trips_when_present(self):
        overlay = {"nodes": [{"id": "criterion:period_valid", "overlay": {"status": "satisfied"}}]}
        resp = DecideResponse.model_validate({"decision": "eligible", "graph_overlay": overlay})
        assert resp.graph_overlay == overlay
