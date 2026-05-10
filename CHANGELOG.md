# Changelog

All notable changes to `aethis-sdk` will be documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.4.5 (2026-05-10)
- fix: update `examples/session.py` to use `AETHIS_RULESET_ID` env var (was deprecated `AETHIS_BUNDLE_ID`) and replace stale internal default with the public `aethis/construction-all-risks` slug

## 0.4.4 (2026-05-07)
- docs: link to the test-driven authoring guide on docs.aethis.ai and surface the publish-gate guarantee (rulesets cannot publish with a failing test) in the private-beta callout. Reference surface only — no code changes

## 0.4.3 (2026-05-06)
- docs: remove positioning paragraph above Install — reference surface (per aethis.os/positioning/surface-types.md); the tagline is enough

## 0.4.2 (2026-05-06)
- docs: add private-beta callout for authoring endpoints (decision endpoints remain anonymous)

## 0.4.1 (2026-05-06)

### Changed
- docs: align README with positioning bible — add problem/solution/methodology intro paragraph before Install section.
- docs: add `aethis-bible:` markers to derived copy blocks (sourced from `public-messaging.md §3/§4`).
- fix: terminology audit found no deprecated "rule bundle" or `<5ms` instances in README; no replacements needed.

## 0.4.0 (2026-05-06)

### Changed
- `Aethis(api_key=...)` and `AsyncAethis(api_key=...)` now accept `api_key=None` (or no argument) for the developer beta. Evaluation endpoints (`/decide`, `/schema`, `/explain`, `/source`) work anonymously, so the SDK no longer forces a key on instantiation. When `api_key` is omitted, the `x-api-key` header is simply not sent. Authoring endpoints will still return 401 without a key. Existing callers passing `api_key="..."` are unaffected.
- README quickstart now shows `Aethis()` (no key) as the primary form, targets `aethis/uk-fsm/child-eligibility` (a live public ruleset) instead of the dated `eng_lang:20250912-ec5d7c23`, and prints the audit fields (`inputs_hash`, `decision_id`, `decision_time`, `engine_version`) added in 0.3.2. Configuration table updated: `api_key` is now documented as optional during the developer beta.
- `examples/oneshot.py` refreshed to match: no key required by default, `AETHIS_BUNDLE_ID` env var renamed to `AETHIS_RULESET_ID` (catching the 0.3.0 `bundle → ruleset` rename it had missed), targets the live UK Free School Meals ruleset, prints the audit fields.

### Notes
- Backwards-compatible: `Aethis(api_key="ak_live_...")` continues to work exactly as before.
- This pairs with the public-surface positioning that evaluation is free during the developer beta — see `docs.aethis.ai`.

## 0.3.2 (2026-05-06)

### Added
- `DecideResponse.decision_id` — per-call audit identifier returned by the engine.
- `DecideResponse.inputs_hash` — canonical SHA-256 fingerprint of the input set.
- `DecideResponse.decision_time` — ISO-8601 timestamp of the decision.
- `DecideResponse.engine_version` — `aethis-core@<semver>` string identifying the engine that produced the decision.

### Fixed
- `DecideResponse` previously declared `ruleset_id` twice; Pydantic silently overrode the first declaration with the second. Deduplicated.
- The four audit fields above were already returned by `/api/v1/public/decide` but were silently dropped by Pydantic because the model didn't declare them. Callers can now read them directly off the typed response — no need to reach for the raw JSON. This is the audit-trail fingerprint that the docs and homepage prominently advertise (`inputs_hash`, `decision_id`); shipping an SDK that hid it was a defect.

### Notes
- Backwards-compatible. All four new fields default to `None`, so older engines that don't emit them still parse cleanly.

## 0.3.1 (2026-05-06)

### Fixed
- `aethis_sdk.__version__` now resolves from installed package metadata via `importlib.metadata` instead of a hardcoded constant. Previously reported `"0.1.0"` on every install regardless of the actual package version. Falls back to `"0.0.0+unknown"` only if the package is imported without being installed (editable dev or zip-on-PYTHONPATH).
- Package description on PyPI: `"…and bundle schemas"` → `"…and ruleset schemas"` to match the v0.3.0 public-surface rename.

### Added
- README PyPI / Python-version / License shields.

## 0.3.0 (2026-05-05)

### Changed (Breaking)
- Renamed the public *bundle* concept to *ruleset* throughout the SDK to match the `aethis-core 0.10.0` API contract. Every `bundle_id` parameter and JSON key is now `ruleset_id`. URL paths inside the client moved from `/api/v1/public/bundles/...` to `/api/v1/public/rulesets/...`. The `Session` constructor now takes `ruleset_id` and exposes `session.ruleset_id` instead of `session.bundle_id`. Class names: `BundleSummary` → `RulesetSummary`.

### Required
- Engine `aethis-core 0.10.0` or newer. Older engines respond at the legacy `/bundles/*` paths and this client will 404. Pin `aethis-sdk==0.2.0` to keep working against an older engine.

## 0.2.0 (2026-04-27)

### Added
- `DecideResponse.slug` — stable, human-readable handle for the ruleset
  (e.g. `aethis/uk-fsm/child-eligibility`). Set when the resolved ruleset
  was published under a slug; `None` otherwise. Prefer this over
  `ruleset_id` for any reference that should survive ruleset regeneration.
- `SchemaResponse.slug` — same handle, surfaced from
  `GET /rulesets/{id}/schema`.

### Notes
- Backwards-compatible. Existing code that reads `ruleset_id` keeps
  working unchanged; `slug` is purely additive.
- Requires the `aethis-core` engine release that surfaces the field in
  `/decide` and `/rulesets/{id}/schema` responses (rolling out 2026-04).
  Older engines will simply leave `slug=None`.

## 0.1.0 (initial)

- Sync + async clients (`Aethis`, `AsyncAethis`) for `/decide`,
  `/rulesets/{id}/schema`, `/me`, `/rulesets/{id}/explain`,
  `/rulesets/{id}/source`.
- Stateful decision adapters (`SyncDecisionSession`, `DecisionSession`).
- Pydantic response models, exception hierarchy
  (`AethisError`, `AethisAPIError`, `AethisUnavailable`,
  `AethisTimeout`).
