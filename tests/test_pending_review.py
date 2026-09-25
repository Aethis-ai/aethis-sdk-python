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
