"""Interactive decision session — asks questions until a decision is reached.

Run with::

    AETHIS_API_KEY=... python examples/session.py
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
    api_key = os.environ.get("AETHIS_API_KEY")
    if not api_key:
        print("AETHIS_API_KEY is required", file=sys.stderr)
        return 1

    bundle_id = os.environ.get("AETHIS_BUNDLE_ID", "eng_lang:20250912-ec5d7c23")

    with Aethis(api_key=api_key) as client:
        schema = client.get_schema(bundle_id)
        session = SyncDecisionSession(bundle_id, client, schema)
        while (nq := session.next_question()) is not None:
            raw = input(f"{nq.question} ").strip()
            if not raw:
                print("Aborted.")
                return 0
            session.answer(nq.field_id, _coerce(nq.field_type, raw))

        status = session.status()
        print(f"Decision: {status.decision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
