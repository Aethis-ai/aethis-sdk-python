"""Replay identity: absence must never look like a valid version.

The wire reports an unresolved version as the literal string ``"unknown"``.
Before this SDK modelled that, ``DecideResponse.ruleset_version`` also
*defaulted* to ``"unknown"`` — so a caller writing an audit record got a
plausible-looking string whether or not the engine had resolved anything, and
two different failure modes (rulebook call, malformed payload) were
indistinguishable from a real ``v3``.

These tests hold the fix at every boundary a response can enter the SDK
through: sync client, async client, and the session helpers built on top.
"""

from __future__ import annotations

import httpx
import pytest

from aethis_sdk import (
    Aethis,
    AethisReplayIdentityError,
    AsyncAethis,
    ContentIdentity,
    DecideResponse,
    ReplayIdentity,
    SchemaResponse,
)
from aethis_sdk.identity import normalise_identity_value
from tests.conftest import make_decide_response, make_schema_response, wire_body

RESOLVED = {
    "ruleset_id": "construction-all-risks:20260412-gold",
    "ruleset_version": "v99",
    "content_digest": "sha256:" + "ab" * 32,
    "engine_version": "aethis-core@0.48.0",
    "decision_id": "dec_abcdefghijklmnop",
    "inputs_hash": "sha256:" + "cd" * 32,
}


def _transport(body: dict) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json=body))


class TestUnresolvedSentinelsCollapseToNone:
    @pytest.mark.parametrize("sentinel", ["unknown", "UNKNOWN", " Unknown ", "", "   ", "none", "null", "n/a"])
    def test_sentinel_is_not_a_version(self, sentinel: str) -> None:
        assert normalise_identity_value(sentinel) is None

    @pytest.mark.parametrize("sentinel", ["unknown", "", "UNKNOWN"])
    def test_decide_response_never_surfaces_the_sentinel(self, sentinel: str) -> None:
        response = DecideResponse.model_validate(make_decide_response(ruleset_version=sentinel))
        assert response.ruleset_version is None
        assert response.content_identity is None
        assert response.replay_identity is None

    def test_a_real_version_survives_untouched(self) -> None:
        response = DecideResponse.model_validate(make_decide_response(ruleset_version="v99"))
        assert response.ruleset_version == "v99"

    def test_non_string_identity_does_not_leak_through(self) -> None:
        response = DecideResponse.model_validate(make_decide_response(ruleset_version=None))
        assert response.ruleset_version is None

    def test_there_is_no_unknown_default(self) -> None:
        """The model must not invent an identity for a payload that has none."""
        response = DecideResponse.model_validate({"decision": "undetermined"})
        assert response.ruleset_version is None
        assert response.content_digest is None
        assert response.replay_identity is None


class TestRequireReplayIdentity:
    def test_returns_a_complete_identity_when_resolved(self) -> None:
        response = DecideResponse.model_validate(make_decide_response(**RESOLVED))
        identity = response.require_replay_identity()
        assert isinstance(identity, ReplayIdentity)
        assert identity.ruleset_version == "v99"
        assert isinstance(identity.content, ContentIdentity)

    @pytest.mark.parametrize(
        "dropped",
        ["ruleset_version", "content_digest", "ruleset_id", "engine_version", "decision_id", "inputs_hash"],
    )
    def test_raises_and_names_the_missing_part(self, dropped: str) -> None:
        payload = make_decide_response(**{**RESOLVED, dropped: None})
        response = DecideResponse.model_validate(payload)
        with pytest.raises(AethisReplayIdentityError) as exc:
            response.require_replay_identity()
        assert exc.value.missing == [dropped]
        assert dropped in str(exc.value)

    def test_the_soft_accessor_never_raises(self) -> None:
        response = DecideResponse.model_validate(make_decide_response(ruleset_version="unknown"))
        assert response.replay_identity is None  # no exception

    def test_a_rulebook_decision_has_no_replay_identity(self) -> None:
        """Rulebook calls report `unknown` until composed identity lands."""
        response = DecideResponse.model_validate(
            make_decide_response(
                ruleset_id=None,
                rulebook_id="rb_kzZ_td0tbKW_OLRB",
                ruleset_version="unknown",
                content_digest=None,
            )
        )
        assert response.rulebook_id == "rb_kzZ_td0tbKW_OLRB"
        assert response.replay_identity is None
        with pytest.raises(AethisReplayIdentityError):
            response.require_replay_identity()


class TestIdentityAcrossClients:
    def test_sync_decide_resolves_identity(self) -> None:
        with Aethis(base_url="http://test", transport=_transport(wire_body("decide_partial"))) as client:
            response = client.decide("aethis/construction-all-risks", {})
        identity = response.require_replay_identity()
        assert identity.content_digest.startswith("sha256:")

    async def test_async_decide_resolves_identity(self) -> None:
        async with AsyncAethis(base_url="http://test", transport=_transport(wire_body("decide_partial"))) as client:
            response = await client.decide("aethis/construction-all-risks", {})
        identity = response.require_replay_identity()
        assert identity.content_digest.startswith("sha256:")

    def test_sync_decide_refuses_to_fabricate_a_version(self) -> None:
        body = {**wire_body("decide_partial"), "ruleset_version": "unknown"}
        with Aethis(base_url="http://test", transport=_transport(body)) as client:
            response = client.decide("aethis/construction-all-risks", {})
        assert response.ruleset_version is None
        with pytest.raises(AethisReplayIdentityError):
            response.require_replay_identity()

    async def test_async_decide_refuses_to_fabricate_a_version(self) -> None:
        body = {**wire_body("decide_partial"), "ruleset_version": "unknown"}
        async with AsyncAethis(base_url="http://test", transport=_transport(body)) as client:
            response = await client.decide("aethis/construction-all-risks", {})
        assert response.ruleset_version is None
        with pytest.raises(AethisReplayIdentityError):
            response.require_replay_identity()


class TestSchemaIdentity:
    def test_schema_exposes_the_content_it_describes(self) -> None:
        schema = SchemaResponse.model_validate(wire_body("schema"))
        identity = schema.require_content_identity()
        assert identity.ruleset_id == schema.ruleset_id
        assert identity.content_digest.startswith("sha256:")

    def test_schema_without_identity_raises_rather_than_defaulting(self) -> None:
        schema = SchemaResponse.model_validate(make_schema_response(ruleset_version="unknown", content_digest=None))
        assert schema.ruleset_version is None
        assert schema.content_identity is None
        with pytest.raises(AethisReplayIdentityError) as exc:
            schema.require_content_identity()
        assert set(exc.value.missing) == {"ruleset_version", "content_digest"}

    async def test_async_schema_identity(self) -> None:
        async with AsyncAethis(base_url="http://test", transport=_transport(wire_body("schema"))) as client:
            schema = await client.get_schema("aethis/construction-all-risks")
        assert schema.require_content_identity().ruleset_version


class TestSessionCarriesIdentity:
    def _client_transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/schema"):
                return httpx.Response(200, json=wire_body("schema"))
            return httpx.Response(200, json=wire_body("decide_partial"))

        return httpx.MockTransport(handler)

    def test_sync_session_status_carries_replay_identity(self) -> None:
        from aethis_sdk import SyncDecisionSession

        with Aethis(base_url="http://test", transport=self._client_transport()) as client:
            schema = client.get_schema("aethis/construction-all-risks")
            session = SyncDecisionSession("aethis/construction-all-risks", client, schema)
            status = session.status()
        assert status.replay_identity is not None
        assert status.replay_identity.ruleset_version == "v99"

    async def test_async_session_status_carries_replay_identity(self) -> None:
        from aethis_sdk import DecisionSession

        async with AsyncAethis(base_url="http://test", transport=self._client_transport()) as client:
            schema = await client.get_schema("aethis/construction-all-risks")
            session = DecisionSession("aethis/construction-all-risks", client, schema)
            status = await session.status()
        assert status.replay_identity is not None
        assert status.replay_identity.ruleset_version == "v99"


class TestContentDigestMustAddressContent:
    """A digest that addresses nothing is the same failure as a fake version.

    The engine constrains ``content_digest`` to ``^sha256:[0-9a-f]{64}$``. An
    audit record pinned to ``md5:...``, a truncated ``sha256:beef``, or
    uppercase hex looks pinned and is not — nothing can be re-derived from it.
    """

    @pytest.mark.parametrize(
        "malformed",
        [
            "md5:" + "ab" * 16,
            "sha256:beef",
            "sha256:" + "ab" * 31,  # 62 hex chars, one byte short
            "sha256:" + "zz" * 32,  # right length, not hex
            "SHA256:" + "AB" * 32,  # right shape, wrong case
            "sha256:" + "ab" * 33,  # too long
            "ab" * 32,  # bare hex, no algorithm
            "not-a-digest",
        ],
    )
    def test_a_malformed_digest_is_absence_not_a_value(self, malformed: str) -> None:
        response = DecideResponse.model_validate(make_decide_response(content_digest=malformed))
        assert response.content_digest is None
        assert response.content_identity is None
        with pytest.raises(AethisReplayIdentityError) as exc:
            response.require_replay_identity()
        assert "content_digest" in exc.value.missing

    def test_a_well_formed_digest_survives(self) -> None:
        digest = "sha256:" + "ab" * 32
        response = DecideResponse.model_validate(make_decide_response(**{**RESOLVED, "content_digest": digest}))
        assert response.content_digest == digest
        assert response.require_replay_identity().content_digest == digest

    def test_the_real_engine_digest_is_accepted(self) -> None:
        """Guard against a pattern so strict it rejects reality."""
        response = DecideResponse.model_validate(wire_body("decide_partial"))
        assert response.require_replay_identity().content_digest == wire_body("decide_partial")["content_digest"]

    def test_schema_and_explain_apply_the_same_rule(self) -> None:
        from aethis_sdk import ExplainResponse

        schema = SchemaResponse.model_validate(make_schema_response(content_digest="md5:" + "ab" * 16))
        assert schema.content_digest is None
        explain = ExplainResponse.model_validate(
            {**wire_body("explain"), "content_digest": "sha256:short"}
        )
        assert explain.content_digest is None
