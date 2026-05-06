"""Tests for DecisionSession and SyncDecisionSession."""

from __future__ import annotations

import httpx
import pytest

from aethis_sdk import (
    Aethis,
    AsyncAethis,
    DecisionSession,
    SchemaField,
    SchemaResponse,
    SyncDecisionSession,
)

from tests.conftest import make_decide_response


SCHEMA = SchemaResponse(
    ruleset_id="test:v1",
    fields=[
        SchemaField(field_id="age", field_type="integer", question="How old are you?"),
        SchemaField(field_id="has_passport", field_type="boolean", question="Do you have a passport?"),
        SchemaField(
            field_id="degree_origin",
            field_type="enum",
            question="Where was your degree awarded?",
            enum_values=["uk", "non_uk"],
        ),
    ],
)


def _counting_handler(responses: list[dict]):
    """Handler that cycles through the given response bodies. Returns (handler, counter)."""
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = min(state["n"], len(responses) - 1)
        state["n"] += 1
        return httpx.Response(200, json=responses[idx])

    return handler, state


def _make_async_session(
    responses: list[dict],
) -> tuple[AsyncAethis, DecisionSession, dict]:
    """Return (client, session, call_counter). Caller is responsible for the client CM."""
    handler, state = _counting_handler(responses)
    client = AsyncAethis(
        api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
    )
    return client, DecisionSession("test:v1", client, SCHEMA), state


def _make_sync_session(
    responses: list[dict],
) -> tuple[Aethis, SyncDecisionSession, dict]:
    """Return (client, session, call_counter). Caller is responsible for the client CM."""
    handler, state = _counting_handler(responses)
    client = Aethis(
        api_key="k", base_url="http://test", transport=httpx.MockTransport(handler)
    )
    return client, SyncDecisionSession("test:v1", client, SCHEMA), state


class TestAnswerAccumulation:
    """State-only tests — no HTTP, no client CM needed."""

    def test_initial_answers_empty(self):
        _, session, _ = _make_async_session([make_decide_response()])
        assert session.answers == {}

    def test_answer_stores_value(self):
        _, session, _ = _make_async_session([make_decide_response()])
        session.answer("age", 25)
        assert session.answers == {"age": 25}

    def test_multiple_answers_accumulate(self):
        _, session, _ = _make_async_session([make_decide_response()])
        session.answer("age", 25)
        session.answer("has_passport", True)
        assert session.answers == {"age": 25, "has_passport": True}

    def test_answer_unknown_field_raises(self):
        _, session, _ = _make_async_session([make_decide_response()])
        with pytest.raises(ValueError, match="Unknown.*nonexistent"):
            session.answer("nonexistent", 42)


class TestAsyncDecisionMapping:
    async def test_eligible(self):
        client, session, _ = _make_async_session([make_decide_response(decision="eligible")])
        async with client:
            assert await session.is_eligible() is True

    async def test_not_eligible(self):
        client, session, _ = _make_async_session([make_decide_response(decision="not_eligible")])
        async with client:
            assert await session.is_eligible() is False

    async def test_undetermined(self):
        client, session, _ = _make_async_session([make_decide_response(decision="undetermined")])
        async with client:
            assert await session.is_eligible() is None


class TestAsyncNextQuestion:
    async def test_returns_schema_field_when_present(self):
        client, session, _ = _make_async_session([
            make_decide_response(next_question={"field_id": "age", "question": "How old?", "weight": 1})
        ])
        async with client:
            field = await session.next_question()
        assert field is not None
        assert field.field_id == "age"
        assert field.field_type == "integer"

    async def test_returns_none_when_no_next_question(self):
        client, session, _ = _make_async_session([make_decide_response(next_question=None)])
        async with client:
            assert await session.next_question() is None

    async def test_builds_fallback_field_if_not_in_schema(self):
        client, session, _ = _make_async_session([
            make_decide_response(next_question={"field_id": "unknown_field", "question": "?", "weight": 1})
        ])
        async with client:
            field = await session.next_question()
        assert field is not None
        assert field.field_id == "unknown_field"
        assert field.field_type == "string"


class TestAsyncStatus:
    async def test_snapshot_returns_decision_and_answered(self):
        client, session, _ = _make_async_session([make_decide_response(decision="eligible")])
        session.answer("age", 25)
        async with client:
            status = await session.status()
        assert status.decision == "eligible"
        assert "age" in status.answered
        assert status.trace is None


class TestCaching:
    async def test_multiple_reads_one_http_call(self):
        client, session, state = _make_async_session([make_decide_response()])
        async with client:
            await session.is_eligible()
            await session.next_question()
            await session.status()
        assert state["n"] == 1

    async def test_answer_invalidates_cache(self):
        client, session, state = _make_async_session([
            make_decide_response(decision="undetermined"),
            make_decide_response(decision="eligible"),
        ])
        async with client:
            await session.is_eligible()
            assert state["n"] == 1
            session.answer("age", 25)
            assert await session.is_eligible() is True
            assert state["n"] == 2

    async def test_trace_refetches_when_cached_has_no_trace(self):
        client, session, state = _make_async_session([
            make_decide_response(),
            make_decide_response(trace={"step": 1}),
        ])
        async with client:
            await session.decide()
            assert state["n"] == 1
            resp = await session.decide(include_trace=True)
            assert state["n"] == 2
            assert resp.trace == {"step": 1}


class TestFieldLookup:
    def test_get_field_returns_schema_field(self):
        _, session, _ = _make_async_session([make_decide_response()])
        field = session.get_field("age")
        assert isinstance(field, SchemaField)
        assert field.field_id == "age"

    def test_get_field_unknown_raises(self):
        _, session, _ = _make_async_session([make_decide_response()])
        with pytest.raises(ValueError, match="nonexistent"):
            session.get_field("nonexistent")

    def test_fields_property_exposes_all(self):
        _, session, _ = _make_async_session([make_decide_response()])
        assert set(session.fields.keys()) == {"age", "has_passport", "degree_origin"}


class TestSyncSession:
    def test_eligible(self):
        client, session, _ = _make_sync_session([make_decide_response(decision="eligible")])
        with client:
            assert session.is_eligible() is True

    def test_answer_invalidates_cache(self):
        client, session, state = _make_sync_session([
            make_decide_response(decision="undetermined"),
            make_decide_response(decision="eligible"),
        ])
        with client:
            session.is_eligible()
            assert state["n"] == 1
            session.answer("age", 25)
            assert session.is_eligible() is True
            assert state["n"] == 2

    def test_status_snapshot(self):
        client, session, _ = _make_sync_session([
            make_decide_response(
                decision="undetermined",
                next_question={"field_id": "age", "question": "?", "weight": 1},
            )
        ])
        with client:
            status = session.status()
        assert status.decision == "undetermined"
        assert status.next_question is not None
        assert status.next_question.field_id == "age"


class TestNoNestedReentry:
    """Regression: entering Aethis twice (once by caller, once by a session that re-enters)
    would previously leak the first ``httpx.Client``. The session no longer touches the
    client lifecycle, so nesting is impossible by construction."""

    def test_session_has_no_context_manager(self):
        _, session, _ = _make_sync_session([make_decide_response()])
        assert not hasattr(session, "__enter__")
        assert not hasattr(session, "__exit__")

    def test_async_session_has_no_context_manager(self):
        _, session, _ = _make_async_session([make_decide_response()])
        assert not hasattr(session, "__aenter__")
        assert not hasattr(session, "__aexit__")
