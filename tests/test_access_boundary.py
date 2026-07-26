"""Auth failures say *which* door was closed.

Two access boundaries exist and a newcomer cannot tell them apart from a bare
``401: missing_api_key``:

* **evaluation** — ``/decide`` on a public ruleset, the ruleset catalogue,
  ``/schema``, ``/explain``. No key needed during the developer beta.
* **authoring** — publishing, projects, rulebooks, ``/me``. Invite only.

So the SDK names the boundary on the exception (``.boundary``) and in the
message, and points at the access-request URL. The 401 envelope under test is
the real one, captured anonymously from the deployed engine.
"""

from __future__ import annotations

import httpx
import pytest

from aethis_sdk import Aethis, AethisAuthError, AethisPermissionError, AsyncAethis
from aethis_sdk.errors import BOUNDARY_AUTHORING, BOUNDARY_EVALUATION, DEVELOPER_ACCESS_URL
from tests.conftest import wire_record

CAPTURED_401 = wire_record("unauthenticated_401")


def _status_transport(status: int, body: dict) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, json=body))


class TestCapturedEnvelope:
    def test_the_engine_really_401s_an_authoring_endpoint_with_no_key(self) -> None:
        assert CAPTURED_401["status"] == 401
        assert CAPTURED_401["body"]["detail"]["reason_code"] == "missing_api_key"


class TestAuthoringBoundary:
    def test_sync_401_labels_the_invite_only_boundary(self) -> None:
        with Aethis(base_url="http://test", transport=_status_transport(401, CAPTURED_401["body"])) as client:
            with pytest.raises(AethisAuthError) as exc:
                client.whoami()
        error = exc.value
        assert error.boundary == BOUNDARY_AUTHORING
        assert error.reason_code == "missing_api_key"
        message = str(error)
        assert "invite-only" in message
        assert "needs no key" in message
        assert DEVELOPER_ACCESS_URL in message

    async def test_async_401_labels_the_invite_only_boundary(self) -> None:
        async with AsyncAethis(base_url="http://test", transport=_status_transport(401, CAPTURED_401["body"])) as c:
            with pytest.raises(AethisAuthError) as exc:
                await c.whoami()
        assert exc.value.boundary == BOUNDARY_AUTHORING
        assert DEVELOPER_ACCESS_URL in str(exc.value)

    def test_rulebook_schema_is_the_authoring_side(self) -> None:
        with Aethis(base_url="http://test", transport=_status_transport(401, CAPTURED_401["body"])) as client:
            with pytest.raises(AethisAuthError) as exc:
                client.get_rulebook_schema("aethis/uk-fsm")
        assert exc.value.boundary == BOUNDARY_AUTHORING

    def test_scope_denial_names_the_boundary_and_keeps_the_engine_hint(self) -> None:
        envelope = {
            "detail": {
                "error": "forbidden",
                "reason_code": "denied_missing_permission",
                "action": "publish",
                "missing_permissions": ["rulesets:write"],
                "message": "Missing required permission.",
                "hint": "Ask an administrator to grant rulesets:write.",
            }
        }
        with Aethis(base_url="http://test", transport=_status_transport(403, envelope)) as client:
            with pytest.raises(AethisPermissionError) as exc:
                client.whoami()
        error = exc.value
        assert error.boundary == BOUNDARY_AUTHORING
        assert error.missing_permissions == ["rulesets:write"]
        assert error.hint == "Ask an administrator to grant rulesets:write."
        assert "invite-only" in str(error)


class TestEvaluationBoundary:
    def test_a_refusal_on_the_read_surface_is_not_the_invite_boundary(self) -> None:
        envelope = {
            "detail": {
                "error": "forbidden",
                "reason_code": "denied_missing_permission",
                "action": "read",
                "missing_permissions": ["rulesets:read"],
                "message": "Missing required permission.",
            }
        }
        with Aethis(base_url="http://test", transport=_status_transport(403, envelope)) as client:
            with pytest.raises(AethisPermissionError) as exc:
                client.get_schema("aethis/construction-all-risks")
        message = str(exc.value)
        assert exc.value.boundary == BOUNDARY_EVALUATION
        assert "needs no key for a public ruleset" in message
        assert DEVELOPER_ACCESS_URL in message


class TestNonAccessFailuresAreNotLabelled:
    def test_a_429_carries_no_boundary(self) -> None:
        from aethis_sdk import AethisRateLimitError

        envelope = {
            "detail": {
                "error": "rate_limit_exceeded",
                "reason_code": "daily_quota_exceeded",
                "message": "Too many requests.",
                "category": "read",
                "tier": "free",
                "limit": 100,
            }
        }
        with Aethis(base_url="http://test", transport=_status_transport(429, envelope)) as client:
            with pytest.raises(AethisRateLimitError) as exc:
                client.get_schema("x")
        assert exc.value.boundary is None
        assert "invite-only" not in str(exc.value)

    def test_a_404_carries_no_boundary(self) -> None:
        from aethis_sdk import AethisAPIError

        with Aethis(base_url="http://test", transport=_status_transport(404, {"detail": "not found"})) as client:
            with pytest.raises(AethisAPIError) as exc:
                client.get_schema("nope")
        assert exc.value.boundary is None


class TestKeyRequiredSubpathsAreNotClaimedByThePrefix:
    """`/rulesets/{id}/source` sits under an evaluation prefix but needs a key.

    Labelling it "evaluation" is worse than not labelling it: it tells a
    developer to go hunting a ruleset-visibility problem for a door that will
    never open to them, because the scope behind it is not issued to external
    keys. This was live behaviour until the prefix match was tightened —
    `/public/rulebooks` had been carved out and `/source` had not.
    """

    def test_get_source_is_labelled_authoring(self) -> None:
        with Aethis(base_url="http://test", transport=_status_transport(401, CAPTURED_401["body"])) as client:
            with pytest.raises(AethisAuthError) as exc:
                client.get_source("aethis/construction-all-risks")
        assert exc.value.boundary == BOUNDARY_AUTHORING
        message = str(exc.value)
        assert "invite-only" in message
        assert "needs no key for a public ruleset" not in message, "must not send the reader hunting visibility"

    async def test_async_get_source_is_labelled_authoring(self) -> None:
        async with AsyncAethis(base_url="http://test", transport=_status_transport(401, CAPTURED_401["body"])) as c:
            with pytest.raises(AethisAuthError) as exc:
                await c.get_source("aethis/construction-all-risks")
        assert exc.value.boundary == BOUNDARY_AUTHORING

    def test_its_sibling_read_paths_are_still_evaluation(self) -> None:
        """The tightening must not sweep the genuinely anonymous paths with it."""
        from aethis_sdk._base import access_boundary

        for path in (
            "/api/v1/public/rulesets/aethis/car/schema",
            "/api/v1/public/rulesets/aethis/car/explain",
            "/api/v1/public/rulesets/aethis/car/graph",
            "/api/v1/public/rulesets",
        ):
            assert access_boundary(path, 401) == BOUNDARY_EVALUATION, path

    def test_every_client_method_gets_a_boundary_on_401(self) -> None:
        """No method may be left unlabelled — that is how /source was missed."""
        from aethis_sdk._base import access_boundary

        paths = [
            "/api/v1/public/decide",
            "/api/v1/public/me",
            "/api/v1/public/usage",
            "/api/v1/public/rulesets",
            "/api/v1/public/rulesets/x/schema",
            "/api/v1/public/rulesets/x/graph",
            "/api/v1/public/rulesets/x/explain",
            "/api/v1/public/rulesets/x/source",
            "/api/v1/public/rulesets/x/explain-failure",
            "/api/v1/public/rulebooks/x/schema",
        ]
        for path in paths:
            assert access_boundary(path, 401) in (BOUNDARY_EVALUATION, BOUNDARY_AUTHORING), path
