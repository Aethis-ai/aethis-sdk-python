"""Pending-review details survive real sync/async transport and session projections."""

import pytest

from aethis_sdk import AethisContractViolation, DecideResponse, PendingReview
from tests.conftest import make_decide_response
from tests.test_session import _make_async_session, _make_sync_session


POINT = {
    "review_id": '["policy",0,"evidence"]',
    "criterion_id": "evidence",
    "section_id": "policy",
    "title": "Evidence review",
    "reason": "A reviewer must check the supporting record.",
}


def _response():
    return make_decide_response(
        decision="undetermined", next_question=None, missing_fields=None,
        undetermined_reason="awaiting_review", pending_reviews=[POINT],
        content_identity="sha256:" + "cd" * 32,
    )


def test_response_preserves_review_identity_without_replacing_leaf_identity():
    response = DecideResponse.model_validate(_response())
    assert response.pending_reviews == [PendingReview(**POINT)]
    assert response.undetermined_reason == "awaiting_review"
    assert response.decision_content_identity == "sha256:" + "cd" * 32
    assert response.content_identity is not None
    assert response.model_dump(by_alias=True)["content_identity"] == response.decision_content_identity
    assert DecideResponse.model_validate(response.model_dump()).decision_content_identity == response.decision_content_identity


def test_old_engine_response_remains_valid():
    response = DecideResponse.model_validate(make_decide_response())
    assert response.pending_reviews is None
    assert response.undetermined_reason is None
    assert response.decision_content_identity is None


def test_sync_session_keeps_pending_review_and_does_not_complete():
    client, session, _ = _make_sync_session([_response()])
    with client:
        status = session.status()
    assert status.pending_reviews == [PendingReview(**POINT)]
    assert status.undetermined_reason == "awaiting_review"
    assert status.decision_content_identity == "sha256:" + "cd" * 32
    assert not status.is_complete


@pytest.mark.asyncio
async def test_async_session_keeps_pending_review_and_does_not_complete():
    client, session, _ = _make_async_session([_response()])
    async with client:
        status = await session.status()
    assert status.pending_reviews == [PendingReview(**POINT)]
    assert status.undetermined_reason == "awaiting_review"
    assert not status.is_complete


@pytest.mark.parametrize("decision", ["eligible", "not_eligible"])
def test_terminal_review_contradiction_is_rejected(decision):
    with pytest.raises(AethisContractViolation):
        DecideResponse.model_validate({**_response(), "decision": decision})


@pytest.mark.parametrize("outcomes", [{"approved": True, "declined": False}, {"true": True, "false": None}])
def test_resolution_survives_decision_and_schema_projections(outcomes):
    from aethis_sdk import ReviewPoint, RulebookSchemaResponse, SchemaResponse

    point = {**POINT, "resolution": {"field_id": "review.record", "outcomes": outcomes}}
    response = DecideResponse.model_validate({**_response(), "pending_reviews": [point]})
    assert response.model_dump()["pending_reviews"][0]["resolution"]["outcomes"] == outcomes
    for model, identity in [(SchemaResponse, {"ruleset_id": "policy:v1"}),
                            (RulebookSchemaResponse, {"rulebook_id": "rb_example"})]:
        schema = model.model_validate({**identity, "fields": [], "review_points": [point]})
        assert schema.review_points == [ReviewPoint(**point)]
        assert model.model_validate_json(schema.model_dump_json()) == schema
        assert schema.model_dump()["review_points"][0]["resolution"]["outcomes"] == outcomes


@pytest.mark.parametrize("bad", [1, 0, "true", "false", "", [], {}])
def test_resolution_does_not_coerce_authored_results(bad):
    from pydantic import ValidationError
    from aethis_sdk import ReviewResolution

    with pytest.raises(ValidationError):
        ReviewResolution(field_id="review.record", outcomes={"approved": bad})


def test_sync_session_preserves_explicit_unresolved_outcome():
    point = {**POINT, "resolution": {"field_id": "review.record", "outcomes": {"true": True, "false": None}}}
    client, session, _ = _make_sync_session([{**_response(), "pending_reviews": [point]}])
    with client:
        status = session.status()
    assert status.pending_reviews[0].resolution.outcomes == {"true": True, "false": None}
    assert not status.is_complete


@pytest.mark.asyncio
async def test_async_session_preserves_explicit_unresolved_outcome():
    point = {**POINT, "resolution": {"field_id": "review.record", "outcomes": {"true": True, "false": None}}}
    client, session, _ = _make_async_session([{**_response(), "pending_reviews": [point]}])
    async with client:
        status = await session.status()
    assert status.pending_reviews[0].resolution.outcomes == {"true": True, "false": None}
    assert not status.is_complete


RELEASE = {
    "release_id": "326b49a1-5d62-4f83-87b2-4cc71d071822",
    "version": 3,
    "content_identity": "sha256:" + "ef" * 32,
    "members": {"policy": {"ruleset_id": "policy:v1", "content_digest": "sha256:" + "ab" * 32}},
}


def test_composed_schema_preserves_full_release_identity():
    from aethis_sdk import RulebookSchemaResponse

    schema = RulebookSchemaResponse(rulebook_id="rb_example", review_points=[POINT], release=RELEASE)
    assert schema.model_dump()["release"] == RELEASE
    assert RulebookSchemaResponse.model_validate_json(schema.model_dump_json()).release == RELEASE


def test_sync_session_preserves_strong_release_identity_separately_from_composition():
    client, session, _ = _make_sync_session([{**_response(), "release": RELEASE}])
    with client:
        status = session.status()
    assert status.release == RELEASE
    assert status.decision_content_identity != status.release["content_identity"]


@pytest.mark.asyncio
async def test_async_session_preserves_strong_release_identity():
    client, session, _ = _make_async_session([{**_response(), "release": RELEASE}])
    async with client:
        status = await session.status()
    assert status.release == RELEASE
