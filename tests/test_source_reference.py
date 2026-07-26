"""Typed ``SourceReference`` round-trips on both explanation surfaces.

Two things are being defended here.

**The DTO itself.** ``SourceReference`` is the shape a caller renders as "here
is the authority this rule cites". The exemplar under test is not hand-written:
``scripts/capture_engine_fixtures.py`` mints it from the engine's own model
class and deep-link builder, and every assertion below re-validates it against
the ``SourceReference`` JSON Schema captured from the same engine's
``/openapi.json``. If the engine's DTO moves, these fail.

**The two envelopes it arrives in.** ``GET /explain`` returns a flat
``criteria`` array; ``POST /decide`` nests criteria under
``explanation.groups[].criteria[]``. A fixture that served the flat shape on
both paths would let a probe pass while being structurally unable to read a
real ``/decide`` response. Each test below therefore builds its payload on the
*captured* body for that endpoint, and the nesting is asserted explicitly.
"""

from __future__ import annotations

import copy

import httpx
import pytest

from aethis_sdk import (
    Aethis,
    AsyncAethis,
    DecideResponse,
    ExplainResponse,
    SourceReference,
)
from tests.conftest import source_reference_exemplar, wire_body
from tests.test_captured_contract import validate_against_engine_schema

EXEMPLAR = source_reference_exemplar()
CRITERION_ID = "period_valid"


def _explain_with_references() -> dict:
    """The captured ``/explain`` body, with the exemplar attached to a criterion.

    The showcase rulesets have not been republished with resolved references
    yet (that is P3), so the reference is grafted onto the real envelope rather
    than invented alongside a fake one.
    """
    body = copy.deepcopy(wire_body("explain"))
    body["criteria"][0]["source_references"] = [copy.deepcopy(EXEMPLAR)]
    return body


def _decide_with_references() -> dict:
    """The captured ``/decide`` body, with the exemplar attached to a nested criterion."""
    body = copy.deepcopy(wire_body("decide_with_explanation"))
    criterion = body["explanation"]["groups"][0]["criteria"][0]
    assert criterion["criterion_id"] == CRITERION_ID
    criterion["source_references"] = [copy.deepcopy(EXEMPLAR)]
    return body


def _transport(body: dict) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json=body))


class TestTheExemplarIsEngineShaped:
    def test_validates_against_the_captured_engine_schema(self) -> None:
        validate_against_engine_schema(EXEMPLAR, "SourceReference")

    def test_carries_the_whole_contract(self) -> None:
        for field in (
            "source_id",
            "title",
            "authority",
            "url",
            "locator",
            "source_version",
            "source_date",
            "content_digest",
            "licence",
            "verified_at",
            "quote",
            "deep_link",
            "schema_version",
        ):
            assert field in EXEMPLAR, field

    def test_target_is_https_and_the_quote_is_verbatim(self) -> None:
        assert EXEMPLAR["url"].startswith("https://")
        assert EXEMPLAR["content_digest"].startswith("sha256:")
        assert EXEMPLAR["quote"]["exact"]

    def test_deep_link_locates_the_quote_in_the_target(self) -> None:
        assert EXEMPLAR["deep_link"].startswith(EXEMPLAR["url"])
        assert "#:~:text=" in EXEMPLAR["deep_link"]


class TestTypedRoundTrip:
    def test_model_parses_and_re_serialises_losslessly(self) -> None:
        reference = SourceReference.model_validate(EXEMPLAR)
        dumped = reference.model_dump(mode="json", exclude_none=False)
        assert dumped["source_id"] == EXEMPLAR["source_id"]
        assert dumped["quote"]["exact"] == EXEMPLAR["quote"]["exact"]
        assert dumped["deep_link"] == EXEMPLAR["deep_link"]
        # ...and what we emit is still contract-valid.
        validate_against_engine_schema(dumped, "SourceReference")

    def test_unknown_future_fields_survive_rather_than_being_dropped(self) -> None:
        """``schema_version`` evolves additively; a v2 field must not break v1."""
        future = {**EXEMPLAR, "artefact_digest": "sha256:" + "ef" * 32, "schema_version": 2}
        reference = SourceReference.model_validate(future)
        assert reference.schema_version == 2
        assert reference.model_dump()["artefact_digest"] == future["artefact_digest"]

    @pytest.mark.parametrize("dropped", ["source_id", "title", "authority", "url", "content_digest", "licence"])
    def test_a_reference_missing_a_required_part_does_not_parse(self, dropped: str) -> None:
        incomplete = {k: v for k, v in EXEMPLAR.items() if k != dropped}
        with pytest.raises(Exception):
            SourceReference.model_validate(incomplete)


class TestExplainSurfaceSync:
    def test_flat_criteria_carry_typed_references(self) -> None:
        with Aethis(base_url="http://test", transport=_transport(_explain_with_references())) as client:
            response = client.get_explanation("aethis/construction-all-risks")
        assert isinstance(response, ExplainResponse)
        references = response.source_references()
        assert list(references) == [CRITERION_ID]
        reference = references[CRITERION_ID][0]
        assert isinstance(reference, SourceReference)
        assert reference.authority == EXEMPLAR["authority"]
        assert reference.quote.exact == EXEMPLAR["quote"]["exact"]

    def test_the_explanation_is_bound_to_resolved_content(self) -> None:
        with Aethis(base_url="http://test", transport=_transport(_explain_with_references())) as client:
            response = client.get_explanation("aethis/construction-all-risks")
        identity = response.require_content_identity()
        assert identity.content_digest == wire_body("explain")["content_digest"]

    def test_raw_explain_still_returns_the_dict(self) -> None:
        with Aethis(base_url="http://test", transport=_transport(_explain_with_references())) as client:
            raw = client.explain("aethis/construction-all-risks")
        assert isinstance(raw, dict)
        assert raw["criteria"][0]["source_references"][0]["source_id"] == EXEMPLAR["source_id"]


class TestExplainSurfaceAsync:
    async def test_flat_criteria_carry_typed_references(self) -> None:
        async with AsyncAethis(base_url="http://test", transport=_transport(_explain_with_references())) as client:
            response = await client.get_explanation("aethis/construction-all-risks")
        reference = response.source_references()[CRITERION_ID][0]
        assert isinstance(reference, SourceReference)
        assert reference.licence == EXEMPLAR["licence"]

    async def test_raw_explain_still_returns_the_dict(self) -> None:
        async with AsyncAethis(base_url="http://test", transport=_transport(_explain_with_references())) as client:
            raw = await client.explain("aethis/construction-all-risks")
        assert isinstance(raw, dict)


class TestDecideSurfaceSync:
    def test_nested_criteria_carry_typed_references(self) -> None:
        with Aethis(base_url="http://test", transport=_transport(_decide_with_references())) as client:
            response = client.decide("aethis/construction-all-risks", {}, include_explanation=True)
        assert isinstance(response, DecideResponse)
        references = response.source_references()
        assert list(references) == [CRITERION_ID]
        assert isinstance(references[CRITERION_ID][0], SourceReference)

    def test_the_typed_explanation_preserves_the_group_nesting(self) -> None:
        with Aethis(base_url="http://test", transport=_transport(_decide_with_references())) as client:
            response = client.decide("aethis/construction-all-risks", {}, include_explanation=True)
        explanation = response.decision_explanation
        assert explanation is not None
        assert explanation.groups, "decide explanations are grouped — a flat parse would empty this"
        assert explanation.groups[0].criteria[0].criterion_id == CRITERION_ID

    def test_a_decision_without_an_explanation_yields_no_references(self) -> None:
        with Aethis(base_url="http://test", transport=_transport(wire_body("decide_partial"))) as client:
            response = client.decide("aethis/construction-all-risks", {})
        assert response.decision_explanation is None
        assert response.source_references() == {}


class TestDecideSurfaceAsync:
    async def test_nested_criteria_carry_typed_references(self) -> None:
        async with AsyncAethis(base_url="http://test", transport=_transport(_decide_with_references())) as client:
            response = await client.decide("aethis/construction-all-risks", {}, include_explanation=True)
        reference = response.source_references()[CRITERION_ID][0]
        assert reference.deep_link == EXEMPLAR["deep_link"]

    async def test_the_typed_explanation_preserves_the_group_nesting(self) -> None:
        async with AsyncAethis(base_url="http://test", transport=_transport(_decide_with_references())) as client:
            response = await client.decide("aethis/construction-all-risks", {}, include_explanation=True)
        explanation = response.decision_explanation
        assert explanation is not None
        assert explanation.groups[0].criteria[0].criterion_id == CRITERION_ID


class TestBothSurfacesAgreeOnTheDto:
    def test_the_same_reference_parses_identically_from_either_envelope(self) -> None:
        explain = ExplainResponse.model_validate(_explain_with_references())
        decide = DecideResponse.model_validate(_decide_with_references())
        from_explain = explain.source_references()[CRITERION_ID][0]
        from_decide = decide.source_references()[CRITERION_ID][0]
        assert from_explain.model_dump() == from_decide.model_dump()

    def test_the_two_envelopes_are_not_the_same_shape(self) -> None:
        """Guards the fixture class that made a sibling probe vacuously green."""
        explain_body = _explain_with_references()
        decide_body = _decide_with_references()
        assert "criteria" in explain_body and "explanation" not in explain_body
        assert "groups" in decide_body["explanation"]
        assert "criteria" not in decide_body["explanation"]
