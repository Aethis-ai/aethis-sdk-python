"""One-shot decision against a published ruleset.

**No API key needed.** Evaluation endpoints — `decide` on a public ruleset,
`get_schema`, `get_explanation`, `list_rulesets` — are anonymous during the
developer beta. Authoring endpoints (publishing rulesets, project and rulebook
endpoints) are invite-only; set ``AETHIS_API_KEY`` only if you have been issued
a key for those. Request access at https://aethis.ai/developer-access.

Run with::

    python examples/oneshot.py

Override the default ruleset with::

    AETHIS_RULESET_ID=aethis/your-ruleset python examples/oneshot.py
"""

from __future__ import annotations

import os

from aethis_sdk import Aethis, AethisReplayIdentityError


def main() -> int:
    # Optional: only needed for the invite-only authoring surface.
    api_key = os.environ.get("AETHIS_API_KEY")
    ruleset_id = os.environ.get("AETHIS_RULESET_ID", "aethis/uk-fsm/child-eligibility")

    with Aethis(api_key=api_key) as client:
        response = client.decide(
            ruleset_id=ruleset_id,
            field_values={
                "child.age": 10,
                "child.school_type": "state_funded",
            },
        )

        # Blocking input errors first. The engine stops proposing questions
        # while any are outstanding, so an empty `next_question` here means
        # "stuck", not "finished".
        if response.has_blocking_errors:
            print("Inputs the engine could not use:")
            for field, message in sorted(response.blocking_errors.items()):
                print(f"  {field}: {message}")
            return 1

        print(f"Decision:       {response.decision}")
        print(f"Final:          {response.is_terminal}")
        print(f"Decision time:  {response.decision_time}")

        # The replay identity — keep this with your own inputs and the decision
        # can be reproduced and audited later.
        try:
            identity = response.require_replay_identity()
        except AethisReplayIdentityError as err:
            print(f"No replayable identity ({', '.join(err.missing)} unresolved)")
        else:
            print(f"Ruleset:        {identity.ruleset_id}@{identity.ruleset_version}")
            print(f"Content digest: {identity.content_digest}")
            print(f"Engine version: {identity.engine_version}")
            print(f"Decision ID:    {identity.decision_id}")
            print(f"Inputs hash:    {identity.inputs_hash}")

        if response.missing_fields:
            print(f"Missing: {', '.join(response.missing_fields)}")
        if response.next_question:
            print(f"Next: {response.next_question.question} ({response.next_question.field_id})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
