"""Immutable identity of the rule artefact a response was produced from.

The engine resolves a published leaf ruleset's identity on every ``/decide``,
``/schema`` and ``/explain`` call: the immutable ``ruleset_id``, the published
``ruleset_version`` label, and the ``content_digest`` of the exact rule content
that was evaluated. That triple is what lets a caller replay — or audit — a
decision later.

Two rules make the identity safe to build on, and both live here:

1. **Absence is modelled as absence.** The wire protocol reports an unresolved
   version as the literal string ``"unknown"`` (a rulebook call, or an artefact
   published before immutable versions existed). A client that carries that
   string forward hands callers something that *looks* like a version and is
   not. :func:`normalise_identity_value` collapses every unresolved sentinel to
   ``None`` at parse time, so the only way to read a version is to read a real
   one — or ``None``.
2. **Using an incomplete identity is an explicit act.** ``require_*`` accessors
   raise :class:`~aethis_sdk.errors.AethisReplayIdentityError` naming exactly
   which parts are missing, rather than returning a partially-populated object
   a caller might persist as an audit record.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

# Wire values that mean "the engine could not resolve this", not a real label.
# Compared case-insensitively after stripping.
UNRESOLVED_SENTINELS = frozenset({"", "unknown", "none", "null", "n/a"})


def normalise_identity_value(value: Any) -> str | None:
    """Return a real identity string, or ``None`` when the wire said "unknown".

    Non-strings (already ``None``, or a malformed number) also collapse to
    ``None`` — a caller can never be handed a non-string masquerading as a
    version label.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if stripped.lower() in UNRESOLVED_SENTINELS:
        return None
    return stripped


class ContentIdentity(BaseModel):
    """The resolved, immutable identity of one published ruleset's content."""

    model_config = ConfigDict(frozen=True)

    ruleset_id: str
    ruleset_version: str
    content_digest: str

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return f"{self.ruleset_id}@{self.ruleset_version} ({self.content_digest})"


class ReplayIdentity(BaseModel):
    """Everything needed to replay one decision, all of it resolved.

    A :class:`ReplayIdentity` only ever exists in a complete state: it is
    constructed exclusively by
    :meth:`~aethis_sdk.models.DecideResponse.require_replay_identity`, which
    refuses to build one when any part is unresolved.
    """

    model_config = ConfigDict(frozen=True)

    decision_id: str
    inputs_hash: str
    engine_version: str
    ruleset_id: str
    ruleset_version: str
    content_digest: str

    @property
    def content(self) -> ContentIdentity:
        return ContentIdentity(
            ruleset_id=self.ruleset_id,
            ruleset_version=self.ruleset_version,
            content_digest=self.content_digest,
        )
