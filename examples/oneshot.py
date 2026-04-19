"""One-shot decision against a published bundle.

Run with::

    AETHIS_API_KEY=... python examples/oneshot.py
"""

from __future__ import annotations

import os
import sys

from aethis_sdk import Aethis


def main() -> int:
    api_key = os.environ.get("AETHIS_API_KEY")
    if not api_key:
        print("AETHIS_API_KEY is required", file=sys.stderr)
        return 1

    bundle_id = os.environ.get("AETHIS_BUNDLE_ID", "eng_lang:20250912-ec5d7c23")

    with Aethis(api_key=api_key) as client:
        response = client.decide(
            bundle_id=bundle_id,
            field_values={
                "nationality": "French",
                "degree_awarded_in_uk": True,
                "degree_conducted_in_english": True,
            },
        )
        print(f"Decision: {response.decision}")
        if response.missing_fields:
            print(f"Missing: {', '.join(response.missing_fields)}")
        if response.next_question:
            print(f"Next: {response.next_question.question} ({response.next_question.field_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
