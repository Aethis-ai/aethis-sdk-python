"""Typed-error contract + parity-comparator unit tests (offline, PR-gated).

These validate the SDK's *mapping* from the public API's structured 401/403/429
error envelopes to typed exceptions carrying ``reason_code`` /
``missing_permissions`` / ``hint``, using ``MockTransport`` bodies shaped exactly
like the ones the deployed staging engine returns (captured 2026-07-15). The
``staging``-marked tests in ``tests/integration/test_typed_errors.py`` prove the
real live responses still have this shape; these prove the mapping, fast and
offline.
"""

from __future__ import annotations

import httpx
import pytest

from aethis_sdk import (
    Aethis,
    AethisAPIError,
    AethisAuthError,
    AethisPermissionError,
    AethisRateLimitError,
)
from tests.conftest import make_decide_response
from tests.shapes import compare_shape

# Error envelopes, byte-for-byte the shape the public API returns (verified live
# on staging.api.aethis.ai, engine 0.43.0, and pinned by the public-API contract
# the diagnostics endpoint serves).
ENVELOPE_401 = {
    "detail": {
        "error": "unauthorized",
        "reason_code": "invalid_api_key",
        "message": "API key is invalid or has been revoked.",
    }
}
ENVELOPE_403 = {
    "detail": {
        "error": "forbidden",
        "reason_code": "denied_missing_permission",
        "action": "scope.projects:write",
        "missing_permissions": ["projects:write"],
        "message": "API key missing required scope: 'projects:write'",
        "hint": "Rule authoring is invite-only private beta. Request access at https://aethis.ai/sign-up",
    }
}
ENVELOPE_429 = {
    "detail": {
        "error": "rate_limit_exceeded",
        "reason_code": "daily_quota_exceeded",
        "category": "decide",
        "tier": "free",
        "limit": 100,
        "message": "Daily quota exceeded for category 'decide'.",
    }
}


def _client_returning(status: int, body: dict) -> Aethis:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return Aethis(base_url="https://api.test", transport=httpx.MockTransport(handler))


class TestTypedErrorMapping:
    def test_401_maps_to_auth_error_with_reason_code(self) -> None:
        with _client_returning(401, ENVELOPE_401) as client:
            with pytest.raises(AethisAuthError) as exc_info:
                client.whoami()
        err = exc_info.value
        assert err.status_code == 401
        assert err.reason_code == "invalid_api_key"
        assert err.missing_permissions == []
        # Still catchable as the base API error (non-breaking widening).
        assert isinstance(err, AethisAPIError)

    def test_403_maps_to_permission_error_with_missing_permissions(self) -> None:
        with _client_returning(403, ENVELOPE_403) as client:
            with pytest.raises(AethisPermissionError) as exc_info:
                client.decide("aethis/x", {})
        err = exc_info.value
        assert err.status_code == 403
        assert err.reason_code == "denied_missing_permission"
        assert err.missing_permissions == ["projects:write"]
        assert err.hint and "aethis.ai/sign-up" in err.hint
        assert isinstance(err, AethisAPIError)

    def test_429_maps_to_rate_limit_error(self) -> None:
        with _client_returning(429, ENVELOPE_429) as client:
            with pytest.raises(AethisRateLimitError) as exc_info:
                client.decide("aethis/x", {})
        err = exc_info.value
        assert err.status_code == 429
        assert err.reason_code == "daily_quota_exceeded"
        # The category/tier/limit remain reachable on the structured detail.
        assert isinstance(err.detail, dict)
        assert err.detail["category"] == "decide"
        assert err.detail["tier"] == "free"
        assert err.detail["limit"] == 100
        assert isinstance(err, AethisAPIError)

    def test_plain_string_detail_still_raises_base_api_error(self) -> None:
        # A 404 with FastAPI's plain-string detail carries no envelope fields.
        with _client_returning(404, {"detail": "Ruleset not found"}) as client:
            with pytest.raises(AethisAPIError) as exc_info:
                client.get_schema("missing:v1")
        err = exc_info.value
        assert type(err) is AethisAPIError  # not one of the typed subclasses
        assert err.status_code == 404
        assert err.reason_code is None
        assert err.missing_permissions == []

    def test_422_validation_list_detail_is_untouched(self) -> None:
        # FastAPI 422 detail is a list of error objects, not the envelope.
        body = {"detail": [{"loc": ["body", "x"], "msg": "field required", "type": "missing"}]}
        with _client_returning(422, body) as client:
            with pytest.raises(AethisAPIError) as exc_info:
                client.decide("aethis/x", {})
        err = exc_info.value
        assert err.status_code == 422
        assert err.reason_code is None
        assert isinstance(err.detail, list)


class TestParityComparator:
    """The comparator that stops the mocked fixtures drifting from reality."""

    def test_identical_shapes_have_no_divergence(self) -> None:
        fixture = make_decide_response()
        assert compare_shape(fixture, make_decide_response()) == []

    def test_live_key_missing_from_fixture_is_flagged(self) -> None:
        fixture = make_decide_response()
        live = make_decide_response()
        live["brand_new_engine_field"] = "surprise"
        div = compare_shape(fixture, live)
        assert any("brand_new_engine_field" in d for d in div)

    def test_renamed_fixture_key_is_flagged(self) -> None:
        # Fail-first proof: rename a fixture key and the live original trips it.
        live = make_decide_response()
        fixture = make_decide_response()
        fixture["verdict"] = fixture.pop("decision")
        div = compare_shape(fixture, live)
        assert any("decision" in d and "missing from fixture" in d for d in div)

    def test_type_change_is_flagged(self) -> None:
        live = make_decide_response()
        fixture = make_decide_response()
        fixture["fields_evaluated"] = "three"  # int -> string
        div = compare_shape(fixture, live)
        assert any("fields_evaluated" in d and "type" in d for d in div)

    def test_conditional_null_field_is_not_a_false_positive(self) -> None:
        # explanation null on one side, populated on the other — allowed.
        fixture = make_decide_response(explanation=None)
        live = make_decide_response(explanation={"decision": "eligible", "groups": []})
        assert compare_shape(fixture, live) == []

    def test_fixture_only_key_is_allowed(self) -> None:
        # A fixture may carry a conditional key a given live call didn't populate.
        fixture = make_decide_response()
        live = make_decide_response()
        del live["explanation"]
        assert compare_shape(fixture, live) == []
