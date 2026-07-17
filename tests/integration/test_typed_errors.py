"""Live 401 / 403 typed-error contract against deployed staging.

The offline ``tests/test_errors.py`` proves the SDK *maps* the structured error
envelopes to typed exceptions; this proves the deployed engine still *emits*
those envelopes, and cross-checks the shape against the public-API contract the
diagnostics endpoint serves. 429 is validated offline only — deliberately exhausting a quota on
every nightly run is neither cheap nor reliable — but its envelope schema is
asserted present in the contract here so a contract change is caught.
"""

from __future__ import annotations

import pytest

from aethis_sdk import Aethis, AethisAuthError, AethisPermissionError
from tests.integration._auth import MintedKey
from tests.integration.conftest import load_contract

pytestmark = pytest.mark.staging


class TestLive401:
    def test_invalid_key_raises_auth_error(self, base_url: str) -> None:
        with Aethis(api_key="ak_live_definitely_invalid_000", base_url=base_url) as client:
            with pytest.raises(AethisAuthError) as exc_info:
                client.whoami()
        err = exc_info.value
        assert err.status_code == 401
        assert err.reason_code == "invalid_api_key"

    def test_missing_key_raises_auth_error(self, base_url: str) -> None:
        # No key at all on a mandatory-auth endpoint → missing_api_key.
        with Aethis(base_url=base_url) as client:
            with pytest.raises(AethisAuthError) as exc_info:
                client.whoami()
        assert exc_info.value.reason_code == "missing_api_key"


class TestLive403:
    def test_reduced_scope_key_raises_permission_error(self, reduced_scope_key: MintedKey, base_url: str) -> None:
        # Prove the reduced-scope mint path works, then force a real scope-gate.
        # ``get_source`` requires ``rulesets:source`` — a scope no self-serve key
        # is granted — so it 403s with the missing scope enumerated. That maps to
        # AethisPermissionError carrying reason_code + missing_permissions.
        assert reduced_scope_key.scopes == ["decide"]
        with Aethis(api_key=reduced_scope_key.full_key, base_url=base_url) as client:
            with pytest.raises(AethisPermissionError) as exc_info:
                client.get_source("construction-all-risks:20260412-gold")
        err = exc_info.value
        assert err.status_code == 403
        assert err.reason_code == "denied_missing_permission"
        assert err.missing_permissions  # non-empty (the scope[s] the key lacked)
        # ``hint`` is present on some 403 envelopes (e.g. authoring scope) and
        # absent on others (source scope); the SDK surfaces it either way, so we
        # only assert the attribute exists, not that it is populated.
        assert hasattr(err, "hint")


class TestContractEnvelopes:
    """Cross-check the deployed contract's error envelopes against what the SDK
    extracts. Skipped-to-red if the contract endpoint isn't deployed yet."""

    def test_contract_declares_401_403_429_envelopes(self, base_url: str) -> None:
        contract = load_contract(base_url)
        envelopes = contract.get("envelopes", {})
        for code in ("401", "403", "429"):
            assert code in envelopes, f"contract missing {code} envelope"
        # The fields the SDK lifts must be declared by the contract.
        env403 = _detail_properties(envelopes["403"])
        assert "reason_code" in env403 and "missing_permissions" in env403
        env429 = _detail_properties(envelopes["429"])
        assert "reason_code" in env429

    def test_contract_default_scopes_match_a_freshly_minted_key(
        self, contract_default_scopes: set[str], minted_key: MintedKey
    ) -> None:
        # The scope-drift class this suite exists to catch: the scopes a fresh
        # key is minted with must equal the contract's declared default set.
        assert set(minted_key.scopes) == contract_default_scopes


@pytest.fixture(scope="session")
def contract_default_scopes(base_url: str) -> set[str]:
    return set(load_contract(base_url).get("default_scopes", []))


def _detail_properties(envelope: dict) -> dict:
    """Return the ``detail`` object's declared properties from an envelope schema."""
    detail = envelope.get("properties", {}).get("detail", {})
    return detail.get("properties", {})
