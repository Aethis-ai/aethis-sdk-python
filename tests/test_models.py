"""Model-level tests — Pydantic schema for /decide and /schema responses."""

from __future__ import annotations

from aethis_sdk import DecideResponse


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
