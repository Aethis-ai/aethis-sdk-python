# Aethis SDK for Python

[![PyPI](https://img.shields.io/pypi/v/aethis-sdk)](https://pypi.org/project/aethis-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/aethis-sdk)](https://pypi.org/project/aethis-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Official Python SDK for the [Aethis](https://aethis.ai) developer API — eligibility decisions, ruleset schemas, and stateful decision sessions.

**Documentation:** [docs.aethis.ai](https://docs.aethis.ai) · [OpenAPI spec](https://docs.aethis.ai/api-reference/openapi.json) · agents via MCP: `claude mcp add aethis -- npx -y aethis-mcp`

> **Authoring is in private beta.** Decision endpoints are public — `Aethis()` works with no key. Authoring endpoints require an invite. The CLI ([aethis-cli](https://pypi.org/project/aethis-cli/)) is the supported authoring path during the beta — see [docs.aethis.ai/recipes/author-a-rule](https://docs.aethis.ai/recipes/author-a-rule) for the test-driven workflow (rulesets cannot publish with a failing test). Request access at [aethis.ai/developer-access](https://aethis.ai/developer-access).

## Install

```bash
uv add aethis-sdk

# Or, for a standalone venv:
uv pip install aethis-sdk
```

Python 3.11+. Requires `httpx` and `pydantic`. SDK v0.5.0+ ships the composed-rulebook decision surface (`decide_rulebook`) and `rulebook_id` on `DecideResponse`.

## Quickstart

Examples below target `aethis/uk-fsm/child-eligibility` — a live public ruleset (UK Free School Meals, child-eligibility section). Browse all live rulesets with `curl https://api.aethis.ai/api/v1/public/rulesets`.

Single-ruleset decision endpoints are anonymous on public rulesets — `Aethis()` works with no key. Composed-rulebook decisions (`decide_rulebook`) and authoring endpoints require an API key. Pass `api_key="ak_live_..."` to `Aethis(...)` for those paths.

### One-shot decision (sync)

```python
from aethis_sdk import Aethis

with Aethis() as client:
    response = client.decide(
        ruleset_id="aethis/uk-fsm/child-eligibility",
        field_values={
            "child.age": 10,
            "child.school_type": "state_funded",
        },
    )
    print(response.decision)        # "eligible" | "not_eligible" | "undetermined"
    print(response.inputs_hash)     # canonical SHA-256 fingerprint of the input set
    print(response.decision_id)     # per-call audit identifier
    print(response.engine_version)  # e.g. "aethis-core@0.27.0"
```

The four audit fields above (`inputs_hash`, `decision_id`, `decision_time`, `engine_version`) ship in 0.3.2+. Same `inputs_hash` always produces the same outcome from the same `engine_version` — store these alongside the decision for a defensible audit trail.

### One-shot decision (async)

```python
import asyncio
from aethis_sdk import AsyncAethis

async def main():
    async with AsyncAethis() as client:
        response = await client.decide(
            ruleset_id="aethis/uk-fsm/child-eligibility",
            field_values={"child.age": 10, "child.school_type": "state_funded"},
        )
        print(response.decision)

asyncio.run(main())
```

### Composed rulebook (requires API key — v0.5.0+)

A Rulebook composes multiple rulesets via an `outcome_logic` expression — e.g. UK FSM's `child_eligibility AND (household_criteria OR universal_infant)`. Hit the whole-form decision with `decide_rulebook`:

```python
from aethis_sdk import Aethis

with Aethis(api_key="ak_live_...") as client:
    response = client.decide_rulebook(
        rulebook_id="aethis/uk-fsm",
        field_values={
            "child.age": 10, "child.year_group": "year_6",
            "child.school_type": "state_funded",
            "household.receives_universal_credit": True,
            "household.annual_net_earnings": 5000,
            "household.receives_income_support": False,
            "household.receives_income_based_jsa": False,
            "household.receives_income_related_esa": False,
            "household.receives_child_tax_credit_only": False,
            "household.receives_nass_support": False,
            "child.is_looked_after": False,
            "child.is_care_leaver": False,
        },
    )
    print(response.decision)      # "eligible"
    print(response.rulebook_id)   # "rb_kzZ_td0tbKW_OLRB" (slug resolved)
```

Rulebook decide is **always** scope-gated by the engine — anonymous callers get HTTP 401, regardless of rulebook visibility. The `decide_rulebook` method and the `rulebook_id` field on `DecideResponse` ship in SDK v0.5.0. `AsyncAethis.decide_rulebook(...)` is the async equivalent.

### Stateful decision session

Accumulate answers locally and query the API only when needed. Cached until an answer changes. The session does not manage the client — the caller keeps the `Aethis` context open for the session's lifetime.

```python
from aethis_sdk import Aethis, SyncDecisionSession

RULESET_ID = "aethis/uk-fsm/child-eligibility"

with Aethis() as client:
    schema = client.get_schema(RULESET_ID)
    session = SyncDecisionSession(RULESET_ID, client, schema)
    session.answer("child.school_type", "state_funded")
    while (nq := session.next_question()) is not None:
        answer = input(f"{nq.question} ")
        session.answer(nq.field_id, answer)
    print("Eligible:", session.is_eligible())
```

Note: `input()` returns a string. For non-string fields (int / bool / enum) coerce the answer before calling `session.answer()` — the API expects the typed value.

### Authoring (requires a key)

```python
with Aethis(api_key="ak_live_...") as client:
    # ruleset publishing endpoints — see the Aethis CLI for the
    # full authoring workflow:
    # https://github.com/Aethis-ai/aethis-cli
    ...
```

The async equivalent is `DecisionSession` — same surface, `await` on the HTTP methods (`decide`, `is_eligible`, `next_question`, `status`).

## What's included

| Import | Purpose |
|---|---|
| `Aethis`, `AsyncAethis` | HTTP clients for `/decide`, `/rulesets/{id}/schema`, `/me`, `/rulesets/{id}/explain`, `/rulesets/{id}/source` |
| `SyncDecisionSession`, `DecisionSession` | Stateful adapters over the stateless `/decide` endpoint |
| `DecideResponse`, `SchemaResponse`, `SchemaField`, `NextQuestion`, `SectionResult` | Pydantic response models |
| `AethisError`, `AethisAPIError`, `AethisUnavailable`, `AethisTimeout` | Exception hierarchy |

## Configuration

- `api_key` — optional during the developer beta for evaluation endpoints (`/decide`, `/schema`, `/explain`, `/source`). Required for authoring endpoints (publishing rulesets, etc.). Provisioned via [aethis.ai](https://aethis.ai).
- `base_url` — defaults to `https://api.aethis.ai`. HTTP is only permitted for `localhost` / `127.0.0.1` or when passing a test `transport`.
- `timeout` — per-request, seconds. Defaults to 5.
- `iam_token` — optional bearer token for Cloud Run service-to-service auth.

## Status

Pre-1.0. The decision surface (`/decide`, `/schema`) is stable; authoring endpoints (projects, rulesets, publishing) are not yet exposed here — use the [Aethis CLI](https://github.com/Aethis-ai/aethis-cli) for those.

## Links

- Issue tracker: https://github.com/Aethis-ai/aethis-sdk-python/issues
- API docs: https://aethis.ai
