"""Recorded-live parity: the mocked fixtures vs the real staging payloads.

The PR-gate suite is only trustworthy if its hand-built fixtures still match what
the engine returns. This lane fetches a real payload for each fixture builder in
``tests/conftest`` and asserts the fixture is a faithful structural superset of
it (via :func:`tests.shapes.compare_shape`). When the engine adds or renames a
field, this turns red and the fixture gets updated — the mocks can't silently
drift from reality.

The comparator itself is unit-tested offline in ``tests/test_errors.py``
(``TestParityComparator``), including the fail-first proof that a deliberate
fixture change is caught.
"""

from __future__ import annotations

import pytest

from aethis_sdk import Aethis
from tests.conftest import make_decide_response, make_ruleset_summary, make_schema_response
from tests.integration._auth import MintedKey
from tests.integration.conftest import SHOWCASE_RULESET_ID, SHOWCASE_SLUG
from tests.shapes import compare_shape

pytestmark = pytest.mark.staging


def _fmt(divergences: list[str]) -> str:
    return "fixture drifted from live staging payload:\n  " + "\n  ".join(divergences)


class TestFixtureParity:
    def test_decide_fixture_matches_live(self, minted_key: MintedKey, base_url: str) -> None:
        with Aethis(api_key=minted_key.full_key, base_url=base_url) as client:
            # include_* so the live payload populates the richest shape.
            live = client._request(  # noqa: SLF001 - raw body needed for shape parity
                "POST",
                "/api/v1/public/decide",
                json={
                    "ruleset_id": SHOWCASE_SLUG,
                    "field_values": {},
                    "include_trace": True,
                    "include_explanation": True,
                },
            ).json()
        divergences = compare_shape(make_decide_response(), live)
        assert divergences == [], _fmt(divergences)

    def test_schema_fixture_matches_live(self, minted_key: MintedKey, base_url: str) -> None:
        with Aethis(api_key=minted_key.full_key, base_url=base_url) as client:
            live = client._request(  # noqa: SLF001
                "GET", f"/api/v1/public/rulesets/{SHOWCASE_RULESET_ID}/schema"
            ).json()
        divergences = compare_shape(make_schema_response(), live)
        assert divergences == [], _fmt(divergences)

    def test_ruleset_summary_fixture_matches_live(self, minted_key: MintedKey, base_url: str) -> None:
        with Aethis(api_key=minted_key.full_key, base_url=base_url) as client:
            live_list = client._request(  # noqa: SLF001
                "GET", "/api/v1/public/rulesets", params={"limit": 1, "offset": 0}
            ).json()
        assert live_list, "staging returned no rulesets to compare against"
        divergences = compare_shape(make_ruleset_summary(), live_list[0])
        assert divergences == [], _fmt(divergences)
