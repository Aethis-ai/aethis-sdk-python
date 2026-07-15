"""Every public method on ``Aethis`` + ``AsyncAethis`` against deployed staging.

The oracle is the deployed engine (Decision 1): each call hits
``staging.api.aethis.ai`` with a freshly-minted key and the response must parse
into the SDK's typed model without error. Public showcase rulesets only.
"""

from __future__ import annotations

import pytest

from aethis_sdk import (
    Aethis,
    AethisAuthError,
    AsyncAethis,
    DecideResponse,
    DecisionSession,
    RulesetSummary,
    SchemaResponse,
    SyncDecisionSession,
)
from aethis_sdk.errors import AethisAPIError
from tests.integration._auth import MintedKey
from tests.integration.conftest import SHOWCASE_RULESET_ID, SHOWCASE_SLUG

pytestmark = pytest.mark.staging


# --------------------------------------------------------------------------- #
# Sync client
# --------------------------------------------------------------------------- #
class TestSyncClientAgainstStaging:
    def test_decide(self, minted_key: MintedKey, base_url: str) -> None:
        with Aethis(api_key=minted_key.full_key, base_url=base_url) as client:
            resp = client.decide(SHOWCASE_SLUG, {})
        assert isinstance(resp, DecideResponse)
        assert resp.decision in ("eligible", "not_eligible", "undetermined")
        assert resp.ruleset_id  # engine echoes the concrete id

    def test_decide_with_explanation_and_trace(self, minted_key: MintedKey, base_url: str) -> None:
        with Aethis(api_key=minted_key.full_key, base_url=base_url) as client:
            resp = client.decide(SHOWCASE_SLUG, {}, include_trace=True, include_explanation=True)
        assert isinstance(resp, DecideResponse)

    def test_list_rulesets(self, minted_key: MintedKey, base_url: str) -> None:
        with Aethis(api_key=minted_key.full_key, base_url=base_url) as client:
            rulesets = client.list_rulesets(limit=5)
        assert rulesets and all(isinstance(r, RulesetSummary) for r in rulesets)

    def test_get_schema(self, minted_key: MintedKey, base_url: str) -> None:
        with Aethis(api_key=minted_key.full_key, base_url=base_url) as client:
            schema = client.get_schema(SHOWCASE_RULESET_ID)
        assert isinstance(schema, SchemaResponse)
        assert schema.fields

    def test_whoami(self, minted_key: MintedKey, base_url: str) -> None:
        with Aethis(api_key=minted_key.full_key, base_url=base_url) as client:
            me = client.whoami()
        assert isinstance(me, dict)
        assert "scopes" in me and "decide" in me["scopes"]

    def test_explain(self, minted_key: MintedKey, base_url: str) -> None:
        with Aethis(api_key=minted_key.full_key, base_url=base_url) as client:
            explained = client.explain(SHOWCASE_RULESET_ID)
        assert isinstance(explained, dict)
        assert "criteria" in explained

    def test_explain_failure(self, minted_key: MintedKey, base_url: str) -> None:
        with Aethis(api_key=minted_key.full_key, base_url=base_url) as client:
            result = client.explain_failure(SHOWCASE_RULESET_ID, {}, expected_outcome="eligible", test_name="e2e")
        assert isinstance(result, dict)

    def test_get_source_is_ownership_gated(self, minted_key: MintedKey, base_url: str) -> None:
        # A public showcase ruleset isn't owned by the fresh key, so source
        # provenance is 403 — exercises the method *and* the typed 4xx path.
        with Aethis(api_key=minted_key.full_key, base_url=base_url) as client:
            with pytest.raises(AethisAPIError) as exc_info:
                client.get_source(SHOWCASE_RULESET_ID)
        assert exc_info.value.status_code in (403, 404)

    def test_decide_rulebook_is_scope_gated_when_anonymous(self, base_url: str) -> None:
        # No public rulebook exists on staging to decide against; the
        # deterministic, documented behaviour is that anonymous rulebook decide
        # is always scope-gated (401). That is what we assert.
        with Aethis(base_url=base_url) as client:
            with pytest.raises(AethisAuthError) as exc_info:
                client.decide_rulebook("aethis/does-not-exist", {})
        assert exc_info.value.status_code == 401

    def test_sync_session_flow(self, minted_key: MintedKey, base_url: str) -> None:
        with Aethis(api_key=minted_key.full_key, base_url=base_url) as client:
            schema = client.get_schema(SHOWCASE_RULESET_ID)
            session = SyncDecisionSession(SHOWCASE_RULESET_ID, client, schema)
            status = session.status()
            assert status.decision in ("eligible", "not_eligible", "undetermined")
            # Answering a real field must not raise (field id comes from schema).
            first_field = next(iter(session.fields))
            session.answer(first_field, _sample_value(schema, first_field))
            assert session.is_eligible() in (True, False, None)


# --------------------------------------------------------------------------- #
# Async client
# --------------------------------------------------------------------------- #
class TestAsyncClientAgainstStaging:
    async def test_decide(self, minted_key: MintedKey, base_url: str) -> None:
        async with AsyncAethis(api_key=minted_key.full_key, base_url=base_url) as client:
            resp = await client.decide(SHOWCASE_SLUG, {})
        assert isinstance(resp, DecideResponse)

    async def test_list_rulesets(self, minted_key: MintedKey, base_url: str) -> None:
        async with AsyncAethis(api_key=minted_key.full_key, base_url=base_url) as client:
            rulesets = await client.list_rulesets(limit=5)
        assert rulesets and all(isinstance(r, RulesetSummary) for r in rulesets)

    async def test_get_schema(self, minted_key: MintedKey, base_url: str) -> None:
        async with AsyncAethis(api_key=minted_key.full_key, base_url=base_url) as client:
            schema = await client.get_schema(SHOWCASE_RULESET_ID)
        assert isinstance(schema, SchemaResponse)

    async def test_whoami(self, minted_key: MintedKey, base_url: str) -> None:
        async with AsyncAethis(api_key=minted_key.full_key, base_url=base_url) as client:
            me = await client.whoami()
        assert "scopes" in me

    async def test_explain(self, minted_key: MintedKey, base_url: str) -> None:
        async with AsyncAethis(api_key=minted_key.full_key, base_url=base_url) as client:
            explained = await client.explain(SHOWCASE_RULESET_ID)
        assert "criteria" in explained

    async def test_explain_failure(self, minted_key: MintedKey, base_url: str) -> None:
        async with AsyncAethis(api_key=minted_key.full_key, base_url=base_url) as client:
            result = await client.explain_failure(SHOWCASE_RULESET_ID, {}, expected_outcome="eligible", test_name="e2e")
        assert isinstance(result, dict)

    async def test_get_source_is_ownership_gated(self, minted_key: MintedKey, base_url: str) -> None:
        async with AsyncAethis(api_key=minted_key.full_key, base_url=base_url) as client:
            with pytest.raises(AethisAPIError) as exc_info:
                await client.get_source(SHOWCASE_RULESET_ID)
        assert exc_info.value.status_code in (403, 404)

    async def test_decide_rulebook_is_scope_gated_when_anonymous(self, base_url: str) -> None:
        async with AsyncAethis(base_url=base_url) as client:
            with pytest.raises(AethisAuthError) as exc_info:
                await client.decide_rulebook("aethis/does-not-exist", {})
        assert exc_info.value.status_code == 401

    async def test_async_session_flow(self, minted_key: MintedKey, base_url: str) -> None:
        async with AsyncAethis(api_key=minted_key.full_key, base_url=base_url) as client:
            schema = await client.get_schema(SHOWCASE_RULESET_ID)
            session = DecisionSession(SHOWCASE_RULESET_ID, client, schema)
            status = await session.status()
            assert status.decision in ("eligible", "not_eligible", "undetermined")
            first_field = next(iter(session.fields))
            session.answer(first_field, _sample_value(schema, first_field))
            assert await session.is_eligible() in (True, False, None)


def _sample_value(schema: SchemaResponse, field_id: str) -> object:
    """A plausible answer for a schema field, from its declared type."""
    field = next(f for f in schema.fields if f.field_id == field_id)
    if field.enum_values:
        return field.enum_values[0]
    return {
        "boolean": True,
        "integer": 1,
        "number": 1,
        "string": "x",
    }.get(field.field_type, "x")
