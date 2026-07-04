"""Model-level tests — Pydantic schema for /decide and /schema responses."""

from __future__ import annotations

from aethis_sdk import (
    DecideResponse,
    FieldNote,
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
        resp = DecideResponse.model_validate(
            {"decision": "eligible", "ruleset_id": "test:v1"}
        )
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
        resp = DecideResponse.model_validate(
            {"decision": "eligible", "explanation": explanation}
        )
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
