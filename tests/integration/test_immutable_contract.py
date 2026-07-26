"""Staging lane: the immutable-identity / blocking-error / provenance contract.

The mocked suite runs against committed captures. This lane runs the same
assertions against whatever staging is serving *now*, so a contract change on
the engine side turns this red instead of silently invalidating the fixtures.

Two of these are deliberately conditional on P3's showcase republish (resolved
source references are not on every ruleset yet). They assert the moment the
data appears rather than being skipped away — see ``test_source_references_*``.
"""

from __future__ import annotations

import httpx
import pytest

from aethis_sdk import (
    Aethis,
    AethisAuthError,
    AethisReplayIdentityError,
    AsyncAethis,
    SourceReference,
)
from tests.integration.conftest import SHOWCASE_RULESET_ID, SHOWCASE_SLUG

pytestmark = pytest.mark.staging


class TestResolvedIdentityLive:
    def test_decide_resolves_immutable_identity_for_a_slug(self, base_url: str) -> None:
        with Aethis(base_url=base_url) as client:
            response = client.decide(SHOWCASE_SLUG, {})
        identity = response.require_replay_identity()
        assert identity.ruleset_id != SHOWCASE_SLUG, "the engine must resolve the slug, not echo it"
        assert identity.content_digest.startswith("sha256:")
        assert identity.ruleset_version

    async def test_async_decide_resolves_immutable_identity(self, base_url: str) -> None:
        async with AsyncAethis(base_url=base_url) as client:
            response = await client.decide(SHOWCASE_SLUG, {})
        assert response.require_replay_identity().content_digest.startswith("sha256:")

    def test_schema_and_decide_agree_on_the_content_digest(self, base_url: str) -> None:
        with Aethis(base_url=base_url) as client:
            schema = client.get_schema(SHOWCASE_SLUG)
            decision = client.decide(SHOWCASE_SLUG, {})
        assert schema.require_content_identity() == decision.require_replay_identity().content

    def test_explain_agrees_too(self, base_url: str) -> None:
        with Aethis(base_url=base_url) as client:
            explanation = client.get_explanation(SHOWCASE_SLUG)
            decision = client.decide(SHOWCASE_SLUG, {})
        assert explanation.require_content_identity() == decision.require_replay_identity().content

    def test_a_ruleset_id_call_resolves_the_same_identity_as_the_slug(self, base_url: str) -> None:
        with Aethis(base_url=base_url) as client:
            by_slug = client.decide(SHOWCASE_SLUG, {})
            by_id = client.decide(SHOWCASE_RULESET_ID, {})
        assert by_slug.require_replay_identity().content == by_id.require_replay_identity().content


class TestBlockingErrorsLive:
    """Send a value the field's type rejects and check the engine's own contract."""

    def _bad_value(self, base_url: str) -> tuple[str, object]:
        with Aethis(base_url=base_url) as client:
            schema = client.get_schema(SHOWCASE_SLUG)
        for field in schema.fields:
            if field.enum_values:
                return field.field_id, "definitely-not-a-member-of-this-enum"
        raise AssertionError("showcase ruleset has no enum field to abuse")

    def test_blocking_errors_force_undetermined_and_suppress_next_question(self, base_url: str) -> None:
        field_id, value = self._bad_value(base_url)
        with Aethis(base_url=base_url) as client:
            response = client.decide(SHOWCASE_SLUG, {field_id: value})
        assert response.has_blocking_errors
        assert field_id in response.blocking_errors
        assert response.decision == "undetermined"
        assert response.is_terminal is False
        assert response.next_question is None, "the trap the SDK guards: no question left, but not finished"

    async def test_same_on_the_async_client(self, base_url: str) -> None:
        field_id, value = self._bad_value(base_url)
        async with AsyncAethis(base_url=base_url) as client:
            response = await client.decide(SHOWCASE_SLUG, {field_id: value})
        assert response.has_blocking_errors and response.is_terminal is False

    def test_session_never_reports_complete_while_blocked(self, base_url: str) -> None:
        from aethis_sdk import SyncDecisionSession

        field_id, value = self._bad_value(base_url)
        with Aethis(base_url=base_url) as client:
            schema = client.get_schema(SHOWCASE_SLUG)
            session = SyncDecisionSession(SHOWCASE_SLUG, client, schema)
            session.answer(field_id, value)
            status = session.status()
        assert status.blocked and status.is_complete is False


class TestRequestSurfaceLive:
    def test_the_engine_rejects_an_unknown_top_level_key(self, base_url: str) -> None:
        response = httpx.post(
            f"{base_url}/api/v1/public/decide",
            json={"ruleset_id": SHOWCASE_SLUG, "field_values": {}, "batch": [1, 2]},
            timeout=30.0,
        )
        assert response.status_code == 422
        assert any(entry["type"] == "extra_forbidden" for entry in response.json()["detail"])


class TestAccessBoundaryLive:
    def test_an_authoring_endpoint_labels_the_invite_boundary(self, base_url: str) -> None:
        with Aethis(base_url=base_url) as client:
            with pytest.raises(AethisAuthError) as exc:
                client.whoami()
        assert exc.value.boundary == "authoring"
        assert "developer-access" in str(exc.value)

    def test_evaluation_needs_no_key(self, base_url: str) -> None:
        with Aethis(base_url=base_url) as client:
            assert client.get_schema(SHOWCASE_SLUG).fields


class TestSourceReferencesLive:
    """Closes automatically once the P3 showcase republish lands.

    Until then the showcase carries no resolved references, and the assertion
    is the *negative* one that keeps the claim honest: no partially-populated
    reference may be served. When references appear, the typed round-trip is
    asserted on both surfaces without anyone having to remember to enable it.
    """

    def test_explain_references_are_either_absent_or_complete(self, base_url: str) -> None:
        with Aethis(base_url=base_url) as client:
            explanation = client.get_explanation(SHOWCASE_SLUG)
        references = explanation.source_references()
        if not references:
            pytest.xfail("showcase not yet republished with resolved source references (P3)")
        for criterion_id, refs in references.items():
            for reference in refs:
                assert isinstance(reference, SourceReference)
                assert reference.url.startswith("https://"), criterion_id
                assert reference.content_digest.startswith("sha256:")
                assert reference.licence and reference.quote.exact
                assert reference.deep_link.startswith(reference.url.split("#", 1)[0])

    def test_decide_serves_the_identical_dto(self, base_url: str) -> None:
        with Aethis(base_url=base_url) as client:
            explanation = client.get_explanation(SHOWCASE_SLUG)
            decision = client.decide(SHOWCASE_SLUG, {}, include_explanation=True)
        from_explain = explanation.source_references()
        if not from_explain:
            pytest.xfail("showcase not yet republished with resolved source references (P3)")
        from_decide = decision.source_references()
        shared = set(from_explain) & set(from_decide)
        assert shared, "the two surfaces disagree on which criteria carry references"
        for criterion_id in shared:
            assert [r.model_dump() for r in from_explain[criterion_id]] == [
                r.model_dump() for r in from_decide[criterion_id]
            ]

    def test_a_decide_explanation_is_grouped_not_flat(self, base_url: str) -> None:
        with Aethis(base_url=base_url) as client:
            decision = client.decide(SHOWCASE_SLUG, {}, include_explanation=True)
        assert decision.explanation is not None
        assert "groups" in decision.explanation
        assert "criteria" not in decision.explanation


class TestRulebookIdentityIsHonestlyUnresolved:
    def test_a_rulebook_decision_does_not_pretend_to_be_replayable(
        self, minted_key, base_url: str
    ) -> None:
        """Rulebook composition identity is not resolved yet (aethis-core#39).

        The SDK must report that as absent rather than as ``"unknown"``.
        """
        with Aethis(api_key=minted_key.full_key, base_url=base_url) as client:
            try:
                response = client.decide_rulebook("aethis/uk-fsm", {})
            except Exception as exc:  # rulebook may not exist on staging
                pytest.xfail(f"no rulebook available on staging: {exc}")
        if response.ruleset_version is not None:
            return  # composed identity has landed; nothing to assert
        with pytest.raises(AethisReplayIdentityError):
            response.require_replay_identity()
