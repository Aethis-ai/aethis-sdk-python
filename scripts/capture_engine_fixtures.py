#!/usr/bin/env python3
"""Capture the engine's real wire payloads into ``tests/fixtures/``.

The mocked test suite is only trustworthy if the bodies it feeds the models are
the bodies the engine actually sends. This script records them from a live
engine rather than letting anyone hand-write an approximation:

* ``tests/fixtures/engine_openapi_subset.json`` — the request/response JSON
  Schemas the SDK models mirror, lifted verbatim from the engine's own
  ``/openapi.json`` (``DecideRequest``, ``DecideResponse``,
  ``ExplainRulesetResponse``, ``ExplainCriterion``, ``SourceReference``,
  ``SourceQuote``, ``NextQuestion``).
* ``tests/fixtures/wire/*.json`` — one file per captured exchange, each holding
  the request that produced it, the status, the response body, and the
  provenance of the capture.

Every capture is anonymous (no key, no credentials) against a public showcase
ruleset, so it can be re-run by anyone and never records tenant data.

Usage (non-interactive, bounded timeouts)::

    uv run python scripts/capture_engine_fixtures.py \
        --base-url https://staging.api.aethis.ai

The ``SourceReference`` exemplar is generated separately, from the engine's own
model class, because no published showcase ruleset carries resolved references
yet::

    uv run python scripts/capture_engine_fixtures.py \
        --engine-source /path/to/aethis-core --exemplar-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
WIRE = FIXTURES / "wire"

DEFAULT_BASE_URL = "https://staging.api.aethis.ai"
# A public, domain-agnostic showcase ruleset. Never an immigration ruleset —
# those execute on the internal engine only.
DEFAULT_RULESET = "aethis/construction-all-risks"

# Component schemas the SDK's models mirror one-for-one. Everything these
# reference transitively is pulled in too (see `_closure`), so the captured
# subset is self-contained and its `$ref`s always resolve.
SCHEMA_ROOTS = (
    "DecideRequest",
    "DecideResponse",
    "ExplainRulesetResponse",
    "ExplainCriterion",
    "SourceReference",
    "SourceQuote",
    "NextQuestion",
)

_REF_PREFIX = "#/components/schemas/"

TIMEOUT = 30.0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch(url: str, method: str = "GET", body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 - https enforced in main()
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:  # 4xx captures are the point of some fixtures
        return exc.code, json.loads(exc.read().decode())


def _referenced_names(node: Any) -> set[str]:
    """Every ``#/components/schemas/X`` name reachable from ``node``."""
    found: set[str] = set()
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
            found.add(ref[len(_REF_PREFIX) :])
        for value in node.values():
            found |= _referenced_names(value)
    elif isinstance(node, list):
        for item in node:
            found |= _referenced_names(item)
    return found


def _strip_examples(node: Any) -> Any:
    """Drop ``examples`` from a captured schema.

    OpenAPI ``examples`` are illustrative only — they carry no structural
    information and JSON-Schema validation ignores them — but they are authored
    prose, so they can carry internal identifiers. The engine's `caller_ref`
    example named a real pilot firm, which then landed in a committed fixture in
    a public repo. Nothing here needs them, so they do not get captured.
    """
    if isinstance(node, dict):
        return {key: _strip_examples(value) for key, value in node.items() if key != "examples"}
    if isinstance(node, list):
        return [_strip_examples(item) for item in node]
    return node


def _closure(schemas: dict[str, Any], roots: tuple[str, ...]) -> dict[str, Any]:
    """The transitive ``$ref`` closure of ``roots`` within ``schemas``."""
    wanted = set(roots)
    frontier = set(roots)
    while frontier:
        current = frontier.pop()
        if current not in schemas:
            raise SystemExit(f"engine is missing referenced schema {current!r}")
        new = _referenced_names(schemas[current]) - wanted
        wanted |= new
        frontier |= new
    return {name: _strip_examples(schemas[name]) for name in sorted(wanted)}


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {path}")


def _capture(
    name: str,
    base_url: str,
    path: str,
    engine_version: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    note: str = "",
) -> dict[str, Any]:
    status, payload = _fetch(f"{base_url}{path}", method=method, body=body)
    record = {
        "provenance": {
            "captured_at": _now(),
            "captured_from": base_url,
            "engine_version": engine_version,
            "anonymous": True,
            "note": note,
        },
        "request": {"method": method, "path": path, "body": body},
        "status": status,
        "body": payload,
    }
    _write(WIRE / f"{name}.json", record)
    return record


def capture_wire(base_url: str, ruleset: str) -> None:
    status, spec = _fetch(f"{base_url}/openapi.json")
    if status != 200:
        raise SystemExit(f"openapi.json returned {status} from {base_url}")
    engine_version = spec["info"]["version"]
    schemas = spec["components"]["schemas"]
    missing = [n for n in SCHEMA_ROOTS if n not in schemas]
    if missing:
        raise SystemExit(f"engine at {base_url} ({engine_version}) is missing schemas: {missing}")
    captured_schemas = _closure(schemas, SCHEMA_ROOTS)

    _write(
        FIXTURES / "engine_openapi_subset.json",
        {
            "provenance": {
                "captured_at": _now(),
                "captured_from": f"{base_url}/openapi.json",
                "engine_version": engine_version,
            },
            "roots": list(SCHEMA_ROOTS),
            "scrubbed": "OpenAPI `examples` are dropped — see _strip_examples()",
            "schemas": captured_schemas,
        },
    )

    _capture(
        "schema",
        base_url,
        f"/api/v1/public/rulesets/{ruleset}/schema",
        engine_version,
        note="Resolved immutable identity on GET /schema (ruleset_version + content_digest).",
    )
    _capture(
        "explain",
        base_url,
        f"/api/v1/public/rulesets/{ruleset}/explain",
        engine_version,
        note="GET /explain returns a FLAT `criteria` array (contrast decide_with_explanation).",
    )
    _capture(
        "decide_partial",
        base_url,
        "/api/v1/public/decide",
        engine_version,
        method="POST",
        body={
            "ruleset_id": ruleset,
            "field_values": {"car.policy.period_valid": True},
            "include_trace": False,
            "include_explanation": False,
            "include_graph_overlay": False,
        },
        note="Undetermined-with-next-question: no blocking errors, replay identity resolved.",
    )
    _capture(
        "decide_blocking_field_errors",
        base_url,
        "/api/v1/public/decide",
        engine_version,
        method="POST",
        body={
            "ruleset_id": ruleset,
            "field_values": {
                "car.property.category": "not_a_valid_enum",
                "car.policy.period_valid": True,
            },
            "include_trace": False,
            "include_explanation": False,
        },
        note=(
            "Blocking field_errors force decision=undetermined AND next_question=null — "
            "the shape a caller could mistake for 'nothing left to ask, so we are done'."
        ),
    )
    _capture(
        "decide_with_explanation",
        base_url,
        "/api/v1/public/decide",
        engine_version,
        method="POST",
        body={
            "ruleset_id": ruleset,
            "field_values": {
                "car.policy.period_valid": True,
                "car.property.category": "permanent_works",
                "car.loss.is_physical": True,
                "car.component.is_defective": False,
                "car.defect.origin": "none",
                "car.claim.is_rectification": False,
                "car.claim.is_access_damage": False,
                "car.damage.consequence_of_failure": False,
                "car.project.value_millions_gbp": 5,
                "car.notification.within_period": True,
                "car.contract.jct_compliant": True,
            },
            "include_explanation": True,
            "include_trace": True,
        },
        note="POST /decide nests the explanation under explanation.groups[].criteria[].",
    )
    _capture(
        "decide_unknown_key_422",
        base_url,
        "/api/v1/public/decide",
        engine_version,
        method="POST",
        body={"ruleset_id": ruleset, "field_values": {}, "batch": [1, 2]},
        note="DecideRequest forbids unknown top-level keys — no fictional request surface.",
    )
    _capture(
        "unauthenticated_401",
        base_url,
        "/api/v1/public/me",
        engine_version,
        note="Structured 401 envelope on an authoring-boundary endpoint called with no key.",
    )


def capture_exemplar(engine_source: Path) -> None:
    """Emit a ``SourceReference`` exemplar produced by the engine's OWN model.

    No published showcase ruleset carries resolved source references yet (that
    lands with the P3 republish), so there is no wire payload to record. The
    next-best evidence is an instance minted by the engine's own
    ``SourceReference`` / ``build_deep_link`` code — not a hand-written guess —
    and mechanically re-validated against the captured OpenAPI schema by
    ``tests/test_source_reference.py``.
    """
    sys.path.insert(0, str(engine_source))
    from aethis_core.public.models.source_reference import SourceQuote, SourceReference
    from aethis_core.public.services.source_resolution import build_deep_link

    url = "https://www.legislation.gov.uk/uksi/2015/51/regulation/4/made"
    quote = SourceQuote(
        exact="A client must make suitable arrangements for managing a project.",
        prefix="Client duties in relation to managing projects",
        suffix="Those arrangements must include",
    )
    reference = SourceReference(
        source_id="CDM2015#reg4(1)",
        title="The Construction (Design and Management) Regulations 2015",
        authority="UK Statutory Instruments",
        url=url,
        locator="regulation 4(1)",
        source_version="2015 No. 51",
        source_date="2015-02-06",
        content_digest="sha256:" + hashlib.sha256(b"aethis-sdk-python fixture exemplar: CDM 2015 reg 4(1)").hexdigest(),
        licence="OGL-UK-3.0",
        verified_at="2026-07-26T00:00:00Z",
        quote=quote,
        media_type="html",
        deep_link=build_deep_link(url, quote, "html", "regulation 4(1)"),
    )
    _write(
        FIXTURES / "source_reference_exemplar.json",
        {
            "provenance": {
                "generated_at": _now(),
                "generated_by": "aethis_core.public.models.source_reference.SourceReference",
                "engine_source_commit": _git_head(engine_source),
                "why_not_a_wire_capture": (
                    "No published showcase ruleset carries resolved source references yet; "
                    "this instance is minted by the engine's own model + deep-link builder and "
                    "re-validated against the captured OpenAPI SourceReference schema."
                ),
            },
            "reference": reference.model_dump(mode="json"),
        },
    )


def _git_head(repo: Path) -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return out.stdout.strip()
    except Exception:  # pragma: no cover - provenance is best-effort
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture engine wire fixtures.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--ruleset", default=DEFAULT_RULESET)
    parser.add_argument("--engine-source", type=Path, default=None, help="path to an aethis-core checkout")
    parser.add_argument("--exemplar-only", action="store_true")
    args = parser.parse_args()

    if not args.base_url.startswith("https://"):
        raise SystemExit("--base-url must be https")

    if not args.exemplar_only:
        capture_wire(args.base_url.rstrip("/"), args.ruleset)
    if args.engine_source is not None:
        capture_exemplar(args.engine_source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
