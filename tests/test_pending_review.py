"""Pending human review: typed review points, resolution, schema catalogue, sessions."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from aethis_sdk import (
    AethisContractViolation,
    DecideResponse,
    PendingReview,
    ReviewPoint,
    ReviewResolution,
    RulebookSchemaResponse,
    SchemaResponse,
)
from tests.conftest import make_decide_response
from tests.test_session import _make_async_session, _make_sync_session

WIRE_IDENTITY = "rulebook:rb_example:alpha=rs_a1:9a1c2f3e4b5d6a7b"

POINT = {
    "review_id": '[null,0,"evidence"]',
    "criterion_id": "evidence",
    "section_id": None,
    "title": "Evidence review",
    "reason": "A reviewer must check the supporting record.",
}
RESOLUTION = {"field_id": "review.record", "outcomes": {"approved": True, "declined": False, "unresolved": None}}


def _pending(**overrides):
    body = make_decide_response(
        decision="undetermined",
        next_question=None,
        missing_fields=None,
        undetermined_reason="awaiting_review",
        pending_reviews=[POINT],
        content_identity=WIRE_IDENTITY,
    )
    body.update(overrides)
    return body


class TestDecideResponse:
    def test_pending_reviews_reason_and_wire_identity_are_retained(self):
        response = DecideResponse.model_validate(_pending())
        assert response.pending_reviews == [PendingReview(**POINT)]
        assert response.undetermined_reason == "awaiting_review"
        assert response.decision_content_identity == WIRE_IDENTITY

    def test_leaf_content_identity_property_is_unchanged(self):
        response = DecideResponse.model_validate(_pending())
        assert response.content_identity is not None
        assert response.content_identity.content_digest == "sha256:" + "ab" * 32

    def test_wire_identity_round_trips_by_alias_and_by_name(self):
        response = DecideResponse.model_validate(_pending())
        assert response.model_dump(by_alias=True)["content_identity"] == WIRE_IDENTITY
        assert DecideResponse.model_validate(response.model_dump()).decision_content_identity == WIRE_IDENTITY
        assert DecideResponse.model_validate_json(response.model_dump_json(by_alias=True)) == response

    def test_response_without_new_fields_remains_valid(self):
        response = DecideResponse.model_validate(make_decide_response())
        assert response.pending_reviews is None
        assert response.undetermined_reason is None
        assert response.decision_content_identity is None

    def test_unknown_future_reason_is_not_rejected(self):
        response = DecideResponse.model_validate(_pending(undetermined_reason="some_future_reason"))
        assert response.undetermined_reason == "some_future_reason"

    @pytest.mark.parametrize("decision", ["eligible", "not_eligible"])
    def test_terminal_decision_beside_pending_reviews_is_rejected(self, decision):
        with pytest.raises(AethisContractViolation):
            DecideResponse.model_validate(_pending(decision=decision, undetermined_reason=None))

    def test_omitted_section_id_parses_as_none(self):
        point = {k: v for k, v in POINT.items() if k != "section_id"}
        entry = DecideResponse.model_validate(_pending(pending_reviews=[point])).pending_reviews[0]
        assert entry.section_id is None

    def test_pending_entry_matches_catalogue_point_by_review_id(self):
        entry = DecideResponse.model_validate(_pending()).pending_reviews[0]
        point = SchemaResponse.model_validate(
            {"ruleset_id": "policy:v1", "fields": [], "review_points": [POINT]}
        ).review_points[0]
        assert entry.review_id == point.review_id
        assert entry != point  # distinct types: join on review_id, not equality

    def test_pending_entry_without_resolution_has_none(self):
        assert DecideResponse.model_validate(_pending()).pending_reviews[0].resolution is None

    def test_pending_entry_carries_resolution_with_null_outcome(self):
        point = {**POINT, "resolution": RESOLUTION}
        entry = DecideResponse.model_validate(_pending(pending_reviews=[point])).pending_reviews[0]
        assert entry.resolution == ReviewResolution(**RESOLUTION)
        assert entry.resolution.outcomes["unresolved"] is None
        assert entry.resolution.outcomes["approved"] is True


class TestReviewResolution:
    def test_null_outcome_survives_serialization(self):
        resolution = ReviewResolution(**RESOLUTION)
        assert resolution.model_dump()["outcomes"] == RESOLUTION["outcomes"]
        assert ReviewResolution.model_validate_json(resolution.model_dump_json()) == resolution
        assert '"unresolved":null' in resolution.model_dump_json()

    @pytest.mark.parametrize("bad", [1, 0, "true", "false", "", [], {}, 1.0])
    def test_outcome_is_never_coerced(self, bad):
        with pytest.raises(ValidationError):
            ReviewResolution(field_id="review.record", outcomes={"approved": bad})

    @pytest.mark.parametrize("bad", [1, None, "", [], {}, b"x"])
    def test_field_id_must_be_a_nonempty_string(self, bad):
        with pytest.raises(ValidationError):
            ReviewResolution(field_id=bad, outcomes={"approved": True})

    def test_outcomes_must_not_be_empty(self):
        with pytest.raises(ValidationError):
            ReviewResolution(field_id="review.record", outcomes={})

    def test_malformed_resolution_inside_a_response_is_rejected(self):
        point = {**POINT, "resolution": {"field_id": "review.record", "outcomes": {"approved": "true"}}}
        with pytest.raises(ValidationError):
            DecideResponse.model_validate(_pending(pending_reviews=[point]))


_SCHEMAS = [
    (SchemaResponse, {"ruleset_id": "policy:v1"}),
    (RulebookSchemaResponse, {"rulebook_id": "rb_example"}),
]


class TestSchemaCatalogue:
    @pytest.mark.parametrize(("model", "identity"), _SCHEMAS)
    def test_review_points_with_and_without_resolution(self, model, identity):
        resolved = {**POINT, "review_id": '[null,1,"other"]', "criterion_id": "other", "resolution": RESOLUTION}
        schema = model.model_validate({**identity, "fields": [], "review_points": [POINT, resolved]})
        assert schema.review_points == [ReviewPoint(**POINT), ReviewPoint(**resolved)]
        assert schema.review_points[0].resolution is None
        assert schema.review_points[1].resolution.outcomes["unresolved"] is None
        assert model.model_validate_json(schema.model_dump_json()) == schema

    @pytest.mark.parametrize(("model", "identity"), _SCHEMAS)
    def test_schema_without_catalogue_is_valid_and_empty(self, model, identity):
        assert model.model_validate({**identity, "fields": []}).review_points == []

    @pytest.mark.parametrize(("model", "identity"), _SCHEMAS)
    def test_malformed_catalogue_resolution_is_rejected(self, model, identity):
        point = {**POINT, "resolution": {"field_id": "review.record", "outcomes": {"approved": 1}}}
        with pytest.raises(ValidationError):
            model.model_validate({**identity, "fields": [], "review_points": [point]})


class TestSessions:
    def test_sync_session_exposes_pending_review_and_is_not_complete(self):
        client, session, _ = _make_sync_session([_pending()])
        with client:
            status = session.status()
        assert status.pending_reviews == [PendingReview(**POINT)]
        assert status.undetermined_reason == "awaiting_review"
        assert status.decision_content_identity == WIRE_IDENTITY
        assert status.has_pending_reviews
        assert not status.is_complete

    async def test_async_session_exposes_pending_review_and_is_not_complete(self):
        client, session, _ = _make_async_session([_pending()])
        async with client:
            status = await session.status()
        assert status.pending_reviews == [PendingReview(**POINT)]
        assert status.undetermined_reason == "awaiting_review"
        assert status.has_pending_reviews
        assert not status.is_complete

    def test_sync_session_keeps_null_resolution_outcome(self):
        point = {**POINT, "resolution": RESOLUTION}
        client, session, _ = _make_sync_session([_pending(pending_reviews=[point])])
        with client:
            status = session.status()
        assert status.pending_reviews[0].resolution.outcomes["unresolved"] is None
        assert not status.is_complete

    async def test_async_session_keeps_null_resolution_outcome(self):
        point = {**POINT, "resolution": RESOLUTION}
        client, session, _ = _make_async_session([_pending(pending_reviews=[point])])
        async with client:
            status = await session.status()
        assert status.pending_reviews[0].resolution.outcomes["unresolved"] is None
        assert not status.is_complete

    def test_session_on_old_response_has_no_pending_reviews(self):
        client, session, _ = _make_sync_session([make_decide_response()])
        with client:
            status = session.status()
        assert status.pending_reviews == []
        assert status.undetermined_reason is None
        assert not status.has_pending_reviews

    def test_terminal_status_cannot_be_built_with_pending_reviews(self):
        from aethis_sdk.session import SessionStatus

        with pytest.raises(AethisContractViolation):
            SessionStatus(
                decision="eligible",
                answered=[],
                next_question=None,
                trace=None,
                pending_reviews=[PendingReview(**POINT)],
            )


def _more_to_ask():
    return _pending(
        undetermined_reason="more_to_ask",
        next_question={"field_id": "age", "question": "How old are you?", "weight": 1, "notes": []},
        missing_fields=["age"],
    )


class TestReviewsBesideQuestions:
    def test_sync_pending_reviews_do_not_hide_next_question(self):
        client, session, _ = _make_sync_session([_more_to_ask()])
        with client:
            status = session.status()
        assert status.has_pending_reviews
        assert status.undetermined_reason == "more_to_ask"
        assert status.next_question is not None
        assert status.next_question.field_id == "age"
        assert not status.is_complete

    async def test_async_pending_reviews_do_not_hide_next_question(self):
        client, session, _ = _make_async_session([_more_to_ask()])
        async with client:
            status = await session.status()
        assert status.has_pending_reviews
        assert status.undetermined_reason == "more_to_ask"
        assert status.next_question is not None
        assert not status.is_complete
