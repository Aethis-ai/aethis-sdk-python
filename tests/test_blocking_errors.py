"""Blocking input errors can never read as a completed or positive result.

The captured payload ``wire/decide_blocking_field_errors.json`` is the exact
trap: the engine reports ``decision="undetermined"``, a populated
``field_errors``, **and** ``next_question: null``. A caller looping
``while session.next_question() is not None`` exits on that payload and, on the
old model, had nothing on ``SessionStatus`` telling it why. It looks identical
to a finished session.

Three boundaries have to hold the line — sync client, async client, and the
session helpers — plus the parse boundary itself, which refuses a payload whose
verdict contradicts its own errors.
"""

from __future__ import annotations

import httpx
import pytest

from aethis_sdk import (
    Aethis,
    AethisContractViolation,
    AethisFieldErrors,
    AsyncAethis,
    DecideResponse,
    DecisionSession,
    SessionStatus,
    SyncDecisionSession,
)
from tests.conftest import make_decide_response, wire_body

BLOCKED = wire_body("decide_blocking_field_errors")


def _decide_transport(body: dict) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/schema"):
            return httpx.Response(200, json=wire_body("schema"))
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handler)


class TestTheCapturedTrap:
    def test_the_engine_really_does_suppress_next_question(self) -> None:
        assert BLOCKED["field_errors"], "fixture no longer exercises the blocking path"
        assert BLOCKED["next_question"] is None
        assert BLOCKED["decision"] == "undetermined"


class TestResponseBoundary:
    def test_blocking_errors_are_always_a_mapping(self) -> None:
        clean = DecideResponse.model_validate(make_decide_response())
        assert clean.blocking_errors == {}
        assert clean.has_blocking_errors is False

    def test_blocked_response_is_not_terminal(self) -> None:
        response = DecideResponse.model_validate(BLOCKED)
        assert response.has_blocking_errors
        assert response.is_terminal is False
        assert response.next_question is None

    def test_clean_verdict_is_terminal(self) -> None:
        response = DecideResponse.model_validate(make_decide_response(decision="eligible", next_question=None))
        assert response.is_terminal is True

    def test_undetermined_without_errors_is_not_terminal(self) -> None:
        response = DecideResponse.model_validate(make_decide_response(decision="undetermined"))
        assert response.is_terminal is False

    def test_raise_for_blocking_errors_chains_when_clean(self) -> None:
        response = DecideResponse.model_validate(make_decide_response(decision="eligible"))
        assert response.raise_for_blocking_errors() is response

    def test_raise_for_blocking_errors_names_every_field(self) -> None:
        response = DecideResponse.model_validate(BLOCKED)
        with pytest.raises(AethisFieldErrors) as exc:
            response.raise_for_blocking_errors()
        assert exc.value.field_errors == BLOCKED["field_errors"]
        for field in BLOCKED["field_errors"]:
            assert field in str(exc.value)


class TestContradictingEnvelopesAreRefused:
    """A conforming engine cannot emit these. A stale build or a proxy can."""

    @pytest.mark.parametrize("decision", ["eligible", "not_eligible"])
    def test_positive_verdict_beside_blocking_errors(self, decision: str) -> None:
        with pytest.raises(AethisContractViolation) as exc:
            DecideResponse.model_validate(make_decide_response(decision=decision, field_errors={"a": "bad"}))
        assert decision in str(exc.value)

    def test_contradicting_embedded_explanation_copy(self) -> None:
        with pytest.raises(AethisContractViolation) as exc:
            DecideResponse.model_validate(
                make_decide_response(
                    decision="undetermined",
                    field_errors={"a": "bad"},
                    explanation={"decision": "eligible", "groups": []},
                )
            )
        assert "explanation.decision" in str(exc.value)

    def test_contradicting_embedded_trace_copy(self) -> None:
        with pytest.raises(AethisContractViolation) as exc:
            DecideResponse.model_validate(
                make_decide_response(
                    decision="undetermined",
                    field_errors={"a": "bad"},
                    trace={"status": "SAT", "answered": {}},
                )
            )
        assert "trace.status" in str(exc.value)

    def test_a_scrubbed_envelope_still_parses(self) -> None:
        """The engine's own scrub must not trip the guard."""
        response = DecideResponse.model_validate(
            make_decide_response(
                decision="undetermined",
                field_errors={"a": "bad"},
                explanation={"decision": "undetermined", "groups": []},
                trace={"status": "UNKNOWN", "answered": {}},
            )
        )
        assert response.has_blocking_errors

    def test_the_guard_fires_on_both_clients(self) -> None:
        """Not a model-only concern: it must hold wherever a response enters."""
        poisoned = {**BLOCKED, "decision": "eligible"}
        with Aethis(base_url="http://test", transport=_decide_transport(poisoned)) as client:
            with pytest.raises(AethisContractViolation):
                client.decide("aethis/construction-all-risks", {})

    async def test_the_guard_fires_on_the_async_client(self) -> None:
        poisoned = {**BLOCKED, "decision": "eligible"}
        async with AsyncAethis(base_url="http://test", transport=_decide_transport(poisoned)) as client:
            with pytest.raises(AethisContractViolation):
                await client.decide("aethis/construction-all-risks", {})


class TestSessionStatusInvariant:
    def test_cannot_construct_a_positive_blocked_status(self) -> None:
        with pytest.raises(AethisContractViolation):
            SessionStatus(
                decision="eligible",
                answered=[],
                next_question=None,
                trace=None,
                field_errors={"a": "bad"},
            )

    def test_blocked_status_is_not_complete(self) -> None:
        status = SessionStatus(
            decision="undetermined",
            answered=["car.policy.period_valid"],
            next_question=None,
            trace=None,
            field_errors={"car.property.category": "bad"},
        )
        assert status.blocked is True
        assert status.is_complete is False
        with pytest.raises(AethisFieldErrors):
            status.raise_if_blocked()

    def test_clean_terminal_status_is_complete(self) -> None:
        status = SessionStatus(decision="eligible", answered=[], next_question=None, trace=None)
        assert status.blocked is False
        assert status.is_complete is True
        assert status.raise_if_blocked() is status

    def test_clean_undetermined_status_is_not_complete(self) -> None:
        status = SessionStatus(decision="undetermined", answered=[], next_question=None, trace=None)
        assert status.is_complete is False


class TestSyncSessionBoundary:
    def _session(self, body: dict) -> tuple[Aethis, SyncDecisionSession]:
        client = Aethis(base_url="http://test", transport=_decide_transport(body))
        client.__enter__()
        schema = client.get_schema("aethis/construction-all-risks")
        return client, SyncDecisionSession("aethis/construction-all-risks", client, schema)

    def test_blocked_session_never_reports_complete(self) -> None:
        client, session = self._session(BLOCKED)
        try:
            assert session.next_question() is None, "the trap: no question left to ask"
            assert session.is_complete() is False
            assert session.blocking_errors() == BLOCKED["field_errors"]
            status = session.status()
            assert status.blocked and not status.is_complete
            assert session.is_eligible() is None
        finally:
            client.close()

    def test_clean_session_reports_complete(self) -> None:
        client, session = self._session(
            {**wire_body("decide_partial"), "decision": "eligible", "next_question": None, "optimal_path": None}
        )
        try:
            assert session.is_complete() is True
            assert session.blocking_errors() == {}
            assert session.is_eligible() is True
        finally:
            client.close()


class TestAsyncSessionBoundary:
    async def test_blocked_session_never_reports_complete(self) -> None:
        async with AsyncAethis(base_url="http://test", transport=_decide_transport(BLOCKED)) as client:
            schema = await client.get_schema("aethis/construction-all-risks")
            session = DecisionSession("aethis/construction-all-risks", client, schema)
            assert await session.next_question() is None
            assert await session.is_complete() is False
            assert await session.blocking_errors() == BLOCKED["field_errors"]
            status = await session.status()
            assert status.blocked and not status.is_complete
            assert await session.is_eligible() is None

    async def test_clean_session_reports_complete(self) -> None:
        body = {
            **wire_body("decide_partial"),
            "decision": "eligible",
            "next_question": None,
            "optimal_path": None,
        }
        async with AsyncAethis(base_url="http://test", transport=_decide_transport(body)) as client:
            schema = await client.get_schema("aethis/construction-all-risks")
            session = DecisionSession("aethis/construction-all-risks", client, schema)
            assert await session.is_complete() is True
            assert await session.is_eligible() is True


class TestTheBeltHoldsWithoutTheBraces:
    """Kill the mutants the validator and the invariant would otherwise mask.

    `is_terminal` and `SessionStatus.is_complete` each carry a blocking-error
    clause that no ordinary test can reach: the parse validator rejects a
    contradicting payload before `is_terminal` sees it, and the constructor
    invariant rejects a contradicting status before `is_complete` sees it. So
    dropping either clause leaves the whole suite green — while removing the
    last thing standing between a bypass route and a wrong answer.

    These build the states the normal paths forbid.
    """

    def test_is_terminal_still_checks_blocking_errors_when_the_validator_is_bypassed(self) -> None:
        # model_construct skips validation entirely — the documented escape
        # hatch, and the one a caller reaching for speed would use.
        response = DecideResponse.model_construct(
            decision="eligible",
            field_errors={"car.property.category": "bad"},
        )
        assert response.has_blocking_errors
        assert response.is_terminal is False, "is_terminal must not rely on the parse validator"

    def test_is_terminal_still_checks_blocking_errors_after_in_place_mutation(self) -> None:
        response = DecideResponse.model_validate(make_decide_response(decision="eligible"))
        assert response.is_terminal is True
        object.__setattr__(response, "field_errors", {"car.property.category": "bad"})
        assert response.is_terminal is False, "a post-parse mutation must not produce a terminal verdict"

    def test_is_complete_still_checks_blocked_when_the_invariant_is_bypassed(self) -> None:
        status = SessionStatus(decision="eligible", answered=[], next_question=None, trace=None)
        assert status.is_complete is True
        # Frozen dataclass: __post_init__ never runs again on this route.
        object.__setattr__(status, "field_errors", {"car.property.category": "bad"})
        assert status.blocked is True
        assert status.is_complete is False, "is_complete must not rely on the constructor invariant"

    def test_is_complete_still_checks_blocked_after_a_dataclass_replace(self) -> None:
        import dataclasses

        clean = SessionStatus(decision="undetermined", answered=[], next_question=None, trace=None)
        blocked = dataclasses.replace(clean, field_errors={"a": "bad"})
        assert blocked.blocked is True
        assert blocked.is_complete is False
