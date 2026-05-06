"""One-shot decision against a published ruleset.

Evaluation endpoints are anonymous during the developer beta — no key
required. Pass AETHIS_API_KEY only if you're calling authoring
endpoints.

Run with::

    python examples/oneshot.py

Override the default ruleset with::

    AETHIS_RULESET_ID=aethis/your-ruleset python examples/oneshot.py
"""

from __future__ import annotations

import os

from aethis_sdk import Aethis


def main() -> int:
    api_key = os.environ.get("AETHIS_API_KEY")  # optional
    ruleset_id = os.environ.get(
        "AETHIS_RULESET_ID", "aethis/uk-fsm/child-eligibility"
    )

    with Aethis(api_key=api_key) as client:
        response = client.decide(
            ruleset_id=ruleset_id,
            field_values={
                "child.age": 10,
                "child.school_type": "state_funded",
            },
        )
        print(f"Decision:       {response.decision}")
        print(f"Inputs hash:    {response.inputs_hash}")
        print(f"Decision ID:    {response.decision_id}")
        print(f"Decision time:  {response.decision_time}")
        print(f"Engine version: {response.engine_version}")
        if response.missing_fields:
            print(f"Missing: {', '.join(response.missing_fields)}")
        if response.next_question:
            print(f"Next: {response.next_question.question} ({response.next_question.field_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
