"""Stateful decision session — accumulates answers and caches ``/decide`` responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aethis_sdk.client import Aethis, AsyncAethis
from aethis_sdk.models import DecideResponse, Decision, SchemaField, SchemaResponse


@dataclass(frozen=True)
class SessionStatus:
    """Typed snapshot of the session state after the latest decision."""

    decision: Decision
    answered: list[str]
    next_question: SchemaField | None
    trace: dict[str, Any] | None


class _SessionState:
    """Shared answer-accumulation and cache logic between sync/async sessions."""

    def __init__(self, bundle_id: str, schema: SchemaResponse) -> None:
        self._bundle_id = bundle_id
        self._answers: dict[str, Any] = {}
        self._cached: DecideResponse | None = None
        self._fields: dict[str, SchemaField] = {f.field_id: f for f in schema.fields}

    @property
    def bundle_id(self) -> str:
        return self._bundle_id

    @property
    def answers(self) -> dict[str, Any]:
        return dict(self._answers)

    @property
    def fields(self) -> dict[str, SchemaField]:
        return dict(self._fields)

    def answer(self, field_id: str, value: Any) -> None:
        """Record an answer for a field. Invalidates any cached decision."""
        if field_id not in self._fields:
            raise ValueError(f"Unknown field: '{field_id}'")
        self._answers[field_id] = value
        self._cached = None

    def get_field(self, field_id: str) -> SchemaField:
        if field_id not in self._fields:
            raise ValueError(f"Field '{field_id}' not found")
        return self._fields[field_id]

    def _needs_fetch(self, include_trace: bool) -> bool:
        if self._cached is None:
            return True
        if include_trace and self._cached.trace is None:
            return True
        return False

    def _build_status(self, resp: DecideResponse) -> SessionStatus:
        next_q: SchemaField | None = None
        if resp.next_question is not None:
            nq = resp.next_question
            next_q = self._fields.get(
                nq.field_id,
                SchemaField(field_id=nq.field_id, field_type="string", question=nq.question),
            )
        return SessionStatus(
            decision=resp.decision,
            answered=list(self._answers.keys()),
            next_question=next_q,
            trace=resp.trace,
        )

    def _resolve_next_question(self, resp: DecideResponse) -> SchemaField | None:
        if resp.next_question is None:
            return None
        nq = resp.next_question
        if nq.field_id in self._fields:
            return self._fields[nq.field_id]
        return SchemaField(field_id=nq.field_id, field_type="string", question=nq.question)

    @staticmethod
    def _decision_to_bool(decision: Decision) -> bool | None:
        if decision == "eligible":
            return True
        if decision == "not_eligible":
            return False
        return None


class DecisionSession(_SessionState):
    """Async stateful decision session over the stateless ``/decide`` endpoint.

    The session holds accumulated answers and caches the last decision; HTTP
    calls are delegated to the supplied :class:`AsyncAethis` client. The caller
    is responsible for the client's lifecycle::

        async with AsyncAethis(api_key="...") as client:
            schema = await client.get_schema("bundle:v1")
            session = DecisionSession("bundle:v1", client, schema)
            session.answer("age", 25)
            if await session.is_eligible():
                print("eligible!")
    """

    def __init__(
        self,
        bundle_id: str,
        client: AsyncAethis,
        schema: SchemaResponse,
    ) -> None:
        super().__init__(bundle_id, schema)
        self._client = client

    async def decide(self, include_trace: bool = False) -> DecideResponse:
        """Return the latest decision. Cached until answers change."""
        if not self._needs_fetch(include_trace):
            assert self._cached is not None
            return self._cached
        resp = await self._client.decide(self._bundle_id, self._answers, include_trace=include_trace)
        self._cached = resp
        return resp

    async def is_eligible(self) -> bool | None:
        """Convenience: ``True``/``False``/``None`` for eligible/not_eligible/undetermined."""
        resp = await self.decide()
        return self._decision_to_bool(resp.decision)

    async def next_question(self) -> SchemaField | None:
        """The next field the API recommends asking about, or ``None`` if the decision is final."""
        resp = await self.decide()
        return self._resolve_next_question(resp)

    async def status(self) -> SessionStatus:
        """Typed snapshot of the current session state."""
        resp = await self.decide()
        return self._build_status(resp)


class SyncDecisionSession(_SessionState):
    """Synchronous stateful decision session.

    The session holds accumulated answers and caches the last decision; HTTP
    calls are delegated to the supplied :class:`Aethis` client. The caller is
    responsible for the client's lifecycle::

        with Aethis(api_key="...") as client:
            schema = client.get_schema("bundle:v1")
            session = SyncDecisionSession("bundle:v1", client, schema)
            session.answer("age", 25)
            if session.is_eligible():
                print("eligible!")
    """

    def __init__(
        self,
        bundle_id: str,
        client: Aethis,
        schema: SchemaResponse,
    ) -> None:
        super().__init__(bundle_id, schema)
        self._client = client

    def decide(self, include_trace: bool = False) -> DecideResponse:
        """Return the latest decision. Cached until answers change."""
        if not self._needs_fetch(include_trace):
            assert self._cached is not None
            return self._cached
        resp = self._client.decide(self._bundle_id, self._answers, include_trace=include_trace)
        self._cached = resp
        return resp

    def is_eligible(self) -> bool | None:
        resp = self.decide()
        return self._decision_to_bool(resp.decision)

    def next_question(self) -> SchemaField | None:
        resp = self.decide()
        return self._resolve_next_question(resp)

    def status(self) -> SessionStatus:
        resp = self.decide()
        return self._build_status(resp)
