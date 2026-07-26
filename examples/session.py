"""Interactive decision session — asks questions until the decision is settled.

**No API key needed.** Driving a public ruleset to a decision is an evaluation
path. ``AETHIS_API_KEY`` is only for the invite-only authoring surface; set it
if you have one, otherwise leave it unset.

Run with::

    python examples/session.py

Note the loop condition. ``next_question()`` returns ``None`` both when the
decision is final *and* when blocking input errors are suppressing further
questions — so looping on it alone would exit a stuck session as if it had
finished. ``status().is_complete`` is the honest test.
"""

from __future__ import annotations

import os
import sys

from aethis_sdk import Aethis, SyncDecisionSession


def _coerce(field_type: str, raw: str) -> object:
    if field_type in ("bool", "boolean"):
        return raw.strip().lower() in ("y", "yes", "true", "1")
    if field_type in ("int", "integer"):
        return int(raw)
    return raw


def main() -> int:
    api_key = os.environ.get("AETHIS_API_KEY")  # optional — evaluation is anonymous
    ruleset_id = os.environ.get("AETHIS_RULESET_ID", "aethis/construction-all-risks")

    with Aethis(api_key=api_key) as client:
        schema = client.get_schema(ruleset_id)
        session = SyncDecisionSession(ruleset_id, client, schema)

        while True:
            status = session.status()

            if status.blocked:
                print("\nThe engine could not use some answers:", file=sys.stderr)
                for field, message in sorted(status.field_errors.items()):
                    print(f"  {field}: {message}", file=sys.stderr)
                return 1

            if status.is_complete:
                print(f"\nDecision: {status.decision}")
                if status.replay_identity is not None:
                    identity = status.replay_identity
                    print(f"Decided against {identity.ruleset_id}@{identity.ruleset_version}")
                    print(f"Content digest: {identity.content_digest}")
                return 0

            question = status.next_question
            if question is None:
                # Not complete, not blocked, nothing left to ask: the ruleset
                # cannot settle on these inputs.
                print(f"\nUndetermined on the answers given ({status.decision}).")
                return 0

            raw = input(f"{question.question} ").strip()
            if not raw:
                print("Aborted.")
                return 0
            session.answer(question.field_id, _coerce(question.field_type, raw))


if __name__ == "__main__":
    raise SystemExit(main())
