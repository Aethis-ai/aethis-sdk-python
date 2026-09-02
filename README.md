# Aethis SDK for Python

[![PyPI](https://img.shields.io/pypi/v/aethis-sdk)](https://pypi.org/project/aethis-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/aethis-sdk)](https://pypi.org/project/aethis-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Official Python SDK for the [Aethis](https://aethis.ai) developer API — eligibility decisions, ruleset schemas, and stateful decision sessions.

**Documentation:** [docs.aethis.ai](https://docs.aethis.ai) · [OpenAPI spec](https://docs.aethis.ai/api-reference/openapi.json) · agents via MCP: `claude mcp add aethis -- npx -y aethis-mcp`

## Two access boundaries

Know which one you are on before you write any code — the SDK will tell you the
same thing in the error message if you cross it.

| | **Evaluation** | **Authoring** |
|---|---|---|
| **Key** | None. `Aethis()` works anonymously. | Invite-only API key. |
| **What** | `decide` on a public ruleset, `list_rulesets`, `get_schema`, `get_graph`, `get_explanation` / `explain`, `get_source`. | Publishing rulesets, project endpoints, rulebook decide + rulebook schema, `whoami`. |
| **If you get it wrong** | — | HTTP 401/403 → `AethisAuthError` / `AethisPermissionError` with `.boundary == "authoring"` and the access-request link in the message. |

Authoring is in private beta. The CLI ([aethis-cli](https://pypi.org/project/aethis-cli/)) is the supported authoring path during the beta — see [docs.aethis.ai/recipes/author-a-rule](https://docs.aethis.ai/recipes/author-a-rule) for the test-driven workflow (rulesets cannot publish with a failing test). Request access at [aethis.ai/developer-access](https://aethis.ai/developer-access).

```python
from aethis_sdk import Aethis, AethisAuthError

with Aethis() as client:                       # evaluation — no key
    client.decide("aethis/construction-all-risks", {...})
    try:
        client.whoami()                        # authoring — needs an invite
    except AethisAuthError as err:
        print(err.boundary)                    # "authoring"
```

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
    if response.has_blocking_errors:
        # Some inputs could not be used. The decision is undetermined and
        # there is no next question — do not read that as "finished".
        raise SystemExit(response.blocking_errors)

    print(response.decision)        # "eligible" | "not_eligible" | "undetermined"
    print(response.is_terminal)     # True only for a clean, unblocked verdict
    print(response.inputs_hash)     # canonical SHA-256 fingerprint of the input set
    print(response.decision_id)     # per-call audit identifier
    print(response.engine_version)  # e.g. "aethis-core@0.48.0"
```

### Blocking input errors

`field_errors` is the structured channel for inputs the engine could not use — an
unknown field key, a value that fails the field's type. Every entry is blocking,
so the decision is always `undetermined`, **and the engine stops proposing a next
question**. That last part is the trap: a blocked response and a finished one
look identical if you only test `next_question is None`.

```python
response = client.decide(RULESET_ID, answers)
if response.has_blocking_errors:
    for field, message in response.blocking_errors.items():
        print(f"{field}: {message}")
elif response.is_terminal:
    print("verdict:", response.decision)
else:
    print("next:", response.next_question.question)

# Or make it an exception instead of a branch:
response.raise_for_blocking_errors()   # raises AethisFieldErrors when blocked
```

The SDK also refuses to parse a response that reports `eligible`/`not_eligible`
beside blocking errors — that contradicts the API contract, so it raises
`AethisContractViolation` rather than handing you a verdict computed from inputs
you did not knowingly send.

### Replay identity

Retain these with your own inputs and a decision can be replayed and audited
later:

```python
identity = response.require_replay_identity()
identity.ruleset_id       # immutable id, never the slug you asked with
identity.ruleset_version  # published version label, e.g. "v99"
identity.content_digest   # sha256 of the exact rule content evaluated
identity.engine_version   # the engine build that decided
identity.decision_id, identity.inputs_hash
```

`require_replay_identity()` raises `AethisReplayIdentityError` — naming the
missing parts — when the engine could not resolve one (a rulebook decision, until
composed identity lands). It never invents a placeholder: `ruleset_version` is
`None` in that case, never the string `"unknown"`. Use `response.replay_identity`
for the non-raising form.

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

    while True:
        status = session.status()
        if status.blocked:                     # inputs the engine could not use
            raise SystemExit(status.field_errors)
        if status.is_complete:                 # a real verdict
            break
        if status.next_question is None:       # undetermined on these answers
            break
        answer = input(f"{status.next_question.question} ")
        session.answer(status.next_question.field_id, answer)

    print("Eligible:", session.is_eligible())
```

**Loop on `status()`, not on `next_question()`.** `next_question()` returns
`None` in three different situations — the decision is final, the ruleset cannot
settle on these answers, or blocking input errors are suppressing further
questions — and `while session.next_question() is not None:` treats all three as
success. `status.blocked` and `status.is_complete` tell them apart:

| | `blocked` | `is_complete` | `next_question` |
|---|---|---|---|
| Still asking | `False` | `False` | a field |
| Finished with a verdict | `False` | `True` | `None` |
| Undetermined on these answers | `False` | `False` | `None` |
| **Blocked by input errors** | **`True`** | **`False`** | **`None`** |

`status.field_errors` is always a dict (empty when clean) and
`status.replay_identity` carries the resolved identity of the content that
decided. `status.raise_if_blocked()` turns the blocked row into an exception if
you would rather not branch.

Note: `input()` returns a string. For non-string fields (int / bool / enum) coerce the answer before calling `session.answer()` — the API expects the typed value.

### Source provenance

Every published citation is fetched, digested, quoted verbatim and licence-checked
at publish time — an unresolvable one blocks the publish. Both explanation
surfaces return the same typed `SourceReference`:

```python
explanation = client.get_explanation(RULESET_ID)   # flat `criteria`
for criterion_id, references in explanation.source_references().items():
    for reference in references:
        print(criterion_id, reference.authority, reference.locator)
        print(reference.quote.exact)   # verbatim, never a summary
        print(reference.deep_link)     # links straight to the quoted passage

decision = client.decide(RULESET_ID, answers, include_explanation=True)
decision.source_references()           # same DTO, from `explanation.groups[].criteria[]`
```

The two envelopes differ — `get_explanation()` returns a flat `criteria` list,
`decide(include_explanation=True)` nests criteria inside groups — so the SDK
models them separately (`ExplainResponse` vs `DecisionExplanation`). Provenance
records *what a rule cites* and that the citation was verified to exist; it is not
a claim that the rule's reading of it is correct.

### Authoring (requires a key)

```python
with Aethis(api_key="ak_live_...") as client:
    status = client.get_generation_status("proj_example")
    if status.job is not None:
        print(status.job.status, status.job.seconds_since_progress)

    # Explicit only: this is a destructive, cooperative request. It releases
    # the project but cannot interrupt an in-flight provider request.
    cancelled = client.cancel_generation("proj_example", status.job.job_id)
    print(cancelled.detail)
```

Use `AsyncAethis` for the same HTTP-client methods with `await`.
`DecisionSession` remains the stateful async helper over `/decide` (`decide`,
`is_eligible`, `next_question`, `status`).

## What's included

| Import | Purpose |
|---|---|
| `Aethis`, `AsyncAethis` | HTTP clients for `/decide`, `/rulesets`, `/rulesets/{id}/schema`, `/rulesets/{id}/graph`, `/rulebooks/{id}/schema`, `/me`, `/rulesets/{id}/explain`, `/rulesets/{id}/source` |
| `decide`, `decide_rulebook` | Single-ruleset and composed-rulebook decisions; both take `include_trace`, `include_explanation`, and `include_graph_overlay` |
| `get_graph` | Fetch a ruleset's field → criterion → group → outcome dependency graph, plus a rendered Mermaid diagram (`GraphResponse`) |
| `get_rulebook_schema` | Fetch a rulebook's combined field schema, plus its `robot_hints` (conversational-agent guidance) and `engine_version` (`RulebookSchemaResponse`) |
| `explain_failure` | Diagnose a mismatched `/decide` — returns the failing criterion and a fix hint |
| `get_generation_status` | Read the latest typed lifecycle telemetry for an authoring project; it never changes the job |
| `cancel_generation` | Explicitly request cooperative cancellation of an observed generation job by project and job id (`GenerationCancellationResponse`) |
| `list_rulesets` | Page the public ruleset catalogue (`RulesetSummary` items) |
| `get_explanation` | Typed ruleset explanation (`ExplainResponse`) with resolved identity and `SourceReference` citations |
| `SyncDecisionSession`, `DecisionSession` | Stateful adapters over the stateless `/decide` endpoint |
| `DecideResponse`, `SchemaResponse`, `RulebookSchemaResponse`, `SchemaField`, `GraphResponse`, `RulesetGraph`, `NextQuestion`, `FieldNote`, `SectionResult`, `RulesetSummary` | Pydantic response models |
| `ExplainResponse`, `ExplainCriterion`, `DecisionExplanation`, `ExplanationGroup`, `ExplanationCriterion` | The two explanation shapes, modelled separately |
| `SourceReference`, `SourceQuote` | Publish-validated citation contract shared by both explanation surfaces |
| `ReplayIdentity`, `ContentIdentity` | Resolved immutable identity of the content a response came from |
| `AethisError`, `AethisAPIError`, `AethisUnavailable`, `AethisTimeout` | Exception hierarchy (`.detail` / `.body` carry the API's error payload; `.boundary` names the access boundary on 401/403) |
| `AethisAuthError` (401), `AethisPermissionError` (403), `AethisRateLimitError` (429) | Typed `AethisAPIError` subclasses carrying `.reason_code`, `.missing_permissions`, `.hint` from the API's structured error envelope |
| `AethisFieldErrors`, `AethisContractViolation`, `AethisReplayIdentityError` | Blocking input errors; a response that contradicts the API contract; an unresolved replay identity |

## Configuration

- `api_key` — **not needed** for evaluation endpoints (`/decide` on a public ruleset, `/rulesets`, `/schema`, `/explain`, `/source`) during the developer beta. **Required, and invite-only**, for authoring endpoints (publishing rulesets, project and rulebook endpoints). Request access at [aethis.ai/developer-access](https://aethis.ai/developer-access).
- `base_url` — defaults to `https://api.aethis.ai`. HTTP is only permitted for `localhost` / `127.0.0.1` or when passing a test `transport`.
- `timeout` — per-request, seconds. Defaults to 5.
- `iam_token` — optional bearer token for Cloud Run service-to-service auth.

## Status

Pre-1.0. The decision surface (`/decide`, `/schema`) is stable. The SDK also
exposes the narrow authoring recovery surface (`get_generation_status` and
explicit `cancel_generation`); it does not submit, resume, or automatically
cancel generation jobs. Use the [Aethis CLI](https://github.com/Aethis-ai/aethis-cli)
for the full authoring workflow.

## Verifying a release

Each published version records the exact bytes it shipped and the commit they
were built from, so you can check that what PyPI serves is what was released:

```bash
uv run python scripts/release_integrity.py --expect integrity.json --verify-registry
```

`integrity.json` (attached to the release run) maps `(package, version)` to each
distribution's sha256 and to the source commit. The same release runs a hermetic
install check — temporary `HOME`, no keys in the environment, empty cache,
registry-only download — across the supported Python / OS / architecture matrix,
plus a poisoned-artefact control that must fail.

## Links

- Issue tracker: https://github.com/Aethis-ai/aethis-sdk-python/issues
- API docs: https://aethis.ai
