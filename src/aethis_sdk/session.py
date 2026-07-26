"""Stateful decision session — accumulates answers and caches ``/decide`` responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aethis_sdk.client import Aethis, AsyncAethis
from aethis_sdk.errors import AethisContractViolation, AethisFieldErrors
from aethis_sdk.identity import ReplayIdentity
from aethis_sdk.models import DecideResponse, Decision, SchemaField, SchemaResponse

_TERMINAL_DECISIONS = ("eligible", "not_eligible")


@dataclass(frozen=True)
class SessionStatus:
    """Typed snapshot of the session state after the latest decision.

    Reading completion off this object is safe by construction:

    * ``field_errors`` is always a mapping (empty when clean), so a blocked
      session can never be mistaken for a clean one by a missing ``None`` check;
    * :attr:`is_complete` is False whenever anything is blocking, regardless of
      what ``next_question`` says. The engine suppresses ``next_question`` when
      blocking errors are present, so "no next question" alone is exactly the
      signal that would misread a blocked session as a finished one;
    * the invariant "blocking errors ⇒ undetermined" is enforced in
      ``__post_init__``, so no code path — including a caller building a status
      by hand — can produce a positive-and-blocked snapshot.
    """

    decision: Decision
    answered: list[str]
    next_question: SchemaField | None
    trace: dict[str, Any] | None
    field_errors: dict[str, str] = field(default_factory=dict)
    replay_identity: ReplayIdentity | None = None

    def __post_init__(self) -> None:
        if self.field_errors and self.decision != "undetermined":
            raise AethisContractViolation(
                f"SessionStatus cannot report decision={self.decision!r} with blocking field "
                f"errors {sorted(self.field_errors)}: blocking input errors always leave the "
                "decision undetermined."
            )

    @property
    def blocked(self) -> bool:
        """True when the latest decision carried blocking input errors."""
        return bool(self.field_errors)

    @property
    def is_complete(self) -> bool:
        """True only for a finished, unblocked session.

        Never infer this from ``next_question is None``.
        """
        return not self.blocked and self.decision in _TERMINAL_DECISIONS

    def raise_if_blocked(self) -> "SessionStatus":
        """Raise :class:`~aethis_sdk.errors.AethisFieldErrors` when blocked;
        return ``self`` otherwise, so it chains."""
        if self.blocked:
            details = "; ".join(f"{k}: {v}" for k, v in sorted(self.field_errors.items()))
            raise AethisFieldErrors(
                f"Session is blocked by {len(self.field_errors)} field error(s) and is not "
                f"complete ({details})",
                field_errors=self.field_errors,
            )
        return self


class _SessionState:
    """Shared answer-accumulation and cache logic between sync/async sessions."""

    def __init__(self, ruleset_id: str, schema: SchemaResponse) -> None:
        self._ruleset_id = ruleset_id
        self._answers: dict[str, Any] = {}
        self._cached: DecideResponse | None = None
        self._fields: dict[str, SchemaField] = {f.field_id: f for f in schema.fields}

    @property
    def ruleset_id(self) -> str:
        return self._ruleset_id

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
        return SessionStatus(
            decision=resp.decision,
            answered=list(self._answers.keys()),
            next_question=self._resolve_next_question(resp),
            trace=resp.trace,
            field_errors=resp.blocking_errors,
            replay_identity=resp.replay_identity,
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
            schema = await client.get_schema("ruleset:v1")
            session = DecisionSession("ruleset:v1", client, schema)
            session.answer("age", 25)
            if await session.is_eligible():
                print("eligible!")
    """

    def __init__(
        self,
        ruleset_id: str,
        client: AsyncAethis,
        schema: SchemaResponse,
    ) -> None:
        super().__init__(ruleset_id, schema)
        self._client = client

    async def decide(self, include_trace: bool = False) -> DecideResponse:
        """Return the latest decision. Cached until answers change."""
        if not self._needs_fetch(include_trace):
            assert self._cached is not None
            return self._cached
        resp = await self._client.decide(self._ruleset_id, self._answers, include_trace=include_trace)
        self._cached = resp
        return resp

    async def is_eligible(self) -> bool | None:
        """Convenience: ``True``/``False``/``None`` for eligible/not_eligible/undetermined."""
        resp = await self.decide()
        return self._decision_to_bool(resp.decision)

    async def next_question(self) -> SchemaField | None:
        """The next field the API recommends asking about.

        ``None`` means either the decision is final **or** blocking input
        errors are suppressing further questions. Use :meth:`is_complete` (or
        :meth:`status`) to tell those apart — they are not the same state.
        """
        resp = await self.decide()
        return self._resolve_next_question(resp)

    async def status(self) -> SessionStatus:
        """Typed snapshot of the current session state."""
        resp = await self.decide()
        return self._build_status(resp)

    async def blocking_errors(self) -> dict[str, str]:
        """Blocking input errors from the latest decision — ``{}`` when clean."""
        resp = await self.decide()
        return resp.blocking_errors

    async def is_complete(self) -> bool:
        """True only when the session reached a verdict with nothing blocking.

        ``await session.next_question() is None`` is **not** equivalent: the
        engine returns no next question while blocking errors are outstanding.
        """
        return (await self.status()).is_complete


class SyncDecisionSession(_SessionState):
    """Synchronous stateful decision session.

    The session holds accumulated answers and caches the last decision; HTTP
    calls are delegated to the supplied :class:`Aethis` client. The caller is
    responsible for the client's lifecycle::

        with Aethis(api_key="...") as client:
            schema = client.get_schema("ruleset:v1")
            session = SyncDecisionSession("ruleset:v1", client, schema)
            session.answer("age", 25)
            if session.is_eligible():
                print("eligible!")
    """

    def __init__(
        self,
        ruleset_id: str,
        client: Aethis,
        schema: SchemaResponse,
    ) -> None:
        super().__init__(ruleset_id, schema)
        self._client = client

    def decide(self, include_trace: bool = False) -> DecideResponse:
        """Return the latest decision. Cached until answers change."""
        if not self._needs_fetch(include_trace):
            assert self._cached is not None
            return self._cached
        resp = self._client.decide(self._ruleset_id, self._answers, include_trace=include_trace)
        self._cached = resp
        return resp

    def is_eligible(self) -> bool | None:
        resp = self.decide()
        return self._decision_to_bool(resp.decision)

    def next_question(self) -> SchemaField | None:
        """The next field the API recommends asking about.

        ``None`` means either the decision is final **or** blocking input
        errors are suppressing further questions — see
        :meth:`DecisionSession.next_question`.
        """
        resp = self.decide()
        return self._resolve_next_question(resp)

    def status(self) -> SessionStatus:
        resp = self.decide()
        return self._build_status(resp)

    def blocking_errors(self) -> dict[str, str]:
        """Blocking input errors from the latest decision — ``{}`` when clean."""
        return self.decide().blocking_errors

    def is_complete(self) -> bool:
        """True only when the session reached a verdict with nothing blocking.

        ``session.next_question() is None`` is **not** equivalent — see
        :meth:`DecisionSession.is_complete`.
        """
        return self.status().is_complete
