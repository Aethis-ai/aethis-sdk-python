# Aethis SDK for Python

Official Python SDK for the [Aethis](https://aethis.ai) developer API — eligibility decisions, bundle schemas, and stateful decision sessions.

## Install

```bash
pip install aethis-sdk
```

Python 3.11+. Requires `httpx` and `pydantic`.

## Quickstart

### One-shot decision (sync)

```python
from aethis_sdk import Aethis

with Aethis(api_key="YOUR_KEY") as client:
    response = client.decide(
        bundle_id="eng_lang:20250912-ec5d7c23",
        field_values={
            "nationality": "French",
            "degree_awarded_in_uk": True,
        },
    )
    print(response.decision)  # "eligible" | "not_eligible" | "undetermined"
```

### One-shot decision (async)

```python
import asyncio
from aethis_sdk import AsyncAethis

async def main():
    async with AsyncAethis(api_key="YOUR_KEY") as client:
        response = await client.decide(
            bundle_id="eng_lang:20250912-ec5d7c23",
            field_values={"nationality": "French"},
        )
        print(response.decision)

asyncio.run(main())
```

### Stateful decision session

Accumulate answers locally and query the API only when needed. Cached until an answer changes. The session does not manage the client — the caller keeps the `Aethis` context open for the session's lifetime.

```python
from aethis_sdk import Aethis, SyncDecisionSession

with Aethis(api_key="YOUR_KEY") as client:
    schema = client.get_schema("eng_lang:20250912-ec5d7c23")
    session = SyncDecisionSession("eng_lang:20250912-ec5d7c23", client, schema)
    session.answer("nationality", "French")
    while (nq := session.next_question()) is not None:
        answer = input(f"{nq.question} ")
        session.answer(nq.field_id, answer)
    print("Eligible:", session.is_eligible())
```

The async equivalent is `DecisionSession` — same surface, `await` on the HTTP methods (`decide`, `is_eligible`, `next_question`, `status`).

## What's included

| Import | Purpose |
|---|---|
| `Aethis`, `AsyncAethis` | HTTP clients for `/decide`, `/bundles/{id}/schema`, `/me`, `/bundles/{id}/explain`, `/bundles/{id}/source` |
| `SyncDecisionSession`, `DecisionSession` | Stateful adapters over the stateless `/decide` endpoint |
| `DecideResponse`, `SchemaResponse`, `SchemaField`, `NextQuestion`, `SectionResult` | Pydantic response models |
| `AethisError`, `AethisAPIError`, `AethisUnavailable`, `AethisTimeout` | Exception hierarchy |

## Configuration

- `api_key` — required. Provisioned via [aethis.ai](https://aethis.ai).
- `base_url` — defaults to `https://api.aethis.ai`. HTTP is only permitted for `localhost` / `127.0.0.1` or when passing a test `transport`.
- `timeout` — per-request, seconds. Defaults to 5.
- `iam_token` — optional bearer token for Cloud Run service-to-service auth.

## Status

Pre-1.0. The decision surface (`/decide`, `/schema`) is stable; authoring endpoints (projects, bundles, publishing) are not yet exposed here — use the [Aethis CLI](https://github.com/Aethis-ai/aethis-cli) for those.

## Links

- Issue tracker: https://github.com/Aethis-ai/aethis-sdk-python/issues
- API docs: https://aethis.ai
