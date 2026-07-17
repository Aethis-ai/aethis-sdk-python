"""Fixtures for the staging integration lane.

Every test in this package is ``@pytest.mark.staging`` (applied module-wide) so
the default PR gate — which runs ``-m 'not staging'`` — never touches the
network. The nightly workflow runs ``-m staging`` with the Clerk creds in the
environment.

A lane that *cannot* run reports red, never green-by-skip. Missing creds,
unreachable staging, or a wedged mint raise :class:`MintUnavailable` from the
session fixture, which errors the staging tests loudly rather than skipping them.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass

import httpx
import pytest

from tests.integration._auth import KeyMinter, MintedKey, StagingConfig

# Public showcase rulesets used across the lane — never immigration / Form AN
# content (that executes internal-only; see immigration-internal-only rule).
SHOWCASE_SLUG = "aethis/construction-all-risks"
SHOWCASE_RULESET_ID = os.environ.get("AETHIS_SHOWCASE_RULESET_ID", "construction-all-risks:20260412-gold")


@pytest.fixture(scope="session")
def staging_config() -> StagingConfig:
    return StagingConfig.from_env()


@pytest.fixture(scope="session")
def key_minter(staging_config: StagingConfig) -> Iterator[KeyMinter]:
    minter = KeyMinter(staging_config)
    try:
        yield minter
    finally:
        minter.teardown()


@pytest.fixture(scope="session")
def run_id() -> str:
    # Prefer the CI run id so leftover keys are traceable to a workflow run.
    return os.environ.get("GITHUB_RUN_ID") or f"local{os.getpid()}"


@pytest.fixture(scope="session")
def minted_key(key_minter: KeyMinter, run_id: str) -> MintedKey:
    """A fresh full-scope key minted the way a user mints one."""
    return key_minter.mint(f"full-{run_id}")


@pytest.fixture(scope="session")
def reduced_scope_key(key_minter: KeyMinter, run_id: str) -> MintedKey:
    """A key holding only ``decide`` — used to force a real 403 on a
    scope-gated endpoint."""
    return key_minter.mint(f"reduced-{run_id}", scopes=["decide"])


@pytest.fixture(scope="session")
def base_url(staging_config: StagingConfig) -> str:
    return staging_config.base_url


@pytest.fixture(scope="session")
def engine_version(base_url: str) -> str:
    """The deployed engine semver, recorded on the qa_runs artifact."""
    try:
        resp = httpx.get(f"{base_url}/openapi.json", timeout=30.0)
        return str(resp.json()["info"]["version"])
    except Exception:  # pragma: no cover - reported as 'unknown' in the artifact
        return "unknown"


@dataclass(frozen=True)
class RulebookFixture:
    rulebook_id: str
    api_key: str
    robot_hints: dict[str, str]


@pytest.fixture(scope="session")
def rulebook_with_robot_hints(minted_key: MintedKey, base_url: str) -> Iterator[RulebookFixture]:
    """A throwaway, empty rulebook (no ruleset_refs) authored with
    ``robot_hints`` — created via a raw ``POST /rulebooks/`` the way the SDK's
    ``get_rulebook_schema`` client method would then read it back, archived on
    teardown. aethis-sdk-python has no rulebook-authoring surface (out of
    scope for #18 — models + read-only ``get_rulebook_schema`` only), so
    fixture creation goes straight through httpx.
    """
    hints = {"general_context": "This is a smoke-test rulebook for SDK model round-trip testing."}
    headers = {"X-API-Key": minted_key.full_key}
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            f"{base_url}/api/v1/public/rulebooks/",
            headers=headers,
            json={"name": "sdk-integration-graph-robot-hints", "domain": "sdk-smoke-test", "robot_hints": hints},
        )
        resp.raise_for_status()
        rulebook_id = resp.json()["rulebook_id"]
        try:
            yield RulebookFixture(rulebook_id=rulebook_id, api_key=minted_key.full_key, robot_hints=hints)
        finally:
            client.post(f"{base_url}/api/v1/public/rulebooks/{rulebook_id}/archive", headers=headers)


def load_contract(base_url: str) -> dict:
    """Fetch the deployed public-API contract (scopes + error envelopes).

    Source is ``AETHIS_CONTRACT_URL`` (default the staging diagnostics route).
    ``AETHIS_CONTRACT_FILE`` may point at the committed aethis-core contract for
    local dev. In CI an unreachable contract raises (red, never skip).
    """
    file_path = os.environ.get("AETHIS_CONTRACT_FILE")
    if file_path:
        import json
        from pathlib import Path

        return json.loads(Path(file_path).read_text())

    url = os.environ.get("AETHIS_CONTRACT_URL", f"{base_url}/api/v1/public/diagnostics/contract")
    resp = httpx.get(url, timeout=30.0)
    resp.raise_for_status()
    return resp.json()
