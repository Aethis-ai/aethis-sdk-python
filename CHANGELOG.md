# Changelog

All notable changes to `aethis-sdk` will be documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## 0.11.0 (2026-07-26)

Makes the SDK a safe, immutable release component for the public developer
release (epic aethis-workspace#643, P9 / aethis-sdk-python#29). Three classes of
"looks fine, isn't" are closed at the type level, and the release itself now
carries verifiable integrity evidence.

### Replay identity: absence no longer looks like a version

- **breaking (behavioural): `DecideResponse.ruleset_version` is `str | None` and no longer defaults to `"unknown"`.** The engine reports an unresolved version as the literal string `"unknown"` (a rulebook call, or an artefact published before immutable versions); the SDK also *defaulted* to that string, so a caller writing an audit record got a plausible-looking version whether or not anything had been resolved. Every unresolved sentinel (`"unknown"`, `""`, `"none"`, `"null"`, `"n/a"`, case-insensitive) now normalises to `None` on `ruleset_version`, `content_digest`, `ruleset_id`, `engine_version`, `decision_id` and `inputs_hash`. Code reading `response.ruleset_version` gets `None` where it previously got `"unknown"`.
- **feat: `content_digest` on `DecideResponse`, and `ruleset_version` + `content_digest` on `SchemaResponse`.** The resolved immutable identity aethis-core stamps on `/decide`, `/schema` and `/explain` (aethis-core#330).
- **feat: `ReplayIdentity` / `ContentIdentity` + `require_replay_identity()` / `require_content_identity()`.** These return a complete identity or raise `AethisReplayIdentityError` naming exactly which parts are unresolved — so recording an incomplete audit reference is an explicit act, not a default. The soft accessors `replay_identity` / `content_identity` return `None` instead of raising.

### Blocking errors cannot become a completed or positive result

- **feat: `DecideResponse.blocking_errors` (always a mapping), `.has_blocking_errors`, `.is_terminal`, `.raise_for_blocking_errors()`.** The engine suppresses `next_question` while blocking `field_errors` are outstanding, so a blocked response is byte-shaped like a finished one on that field. `is_terminal` is the honest check.
- **feat: the parse boundary refuses a self-contradicting envelope.** A 2xx reporting `eligible`/`not_eligible` beside non-empty `field_errors` — or an embedded copy in `explanation.decision` / `trace.status` that contradicts the headline — raises the new `AethisContractViolation` rather than becoming an object a caller acts on. Enforced in the model, so it holds on the sync client, the async client and the sessions alike.
- **feat: `SessionStatus` gains `field_errors`, `replay_identity`, `.blocked`, `.is_complete` and `.raise_if_blocked()`,** with a constructor invariant that makes a positive-and-blocked status unconstructible. Sessions gain `blocking_errors()` and `is_complete()` (sync and async).
- **feat: new `AethisFieldErrors` exception** carrying `.field_errors`, raised by the opt-in `raise_for_blocking_errors()` / `raise_if_blocked()` guards.

### Typed source provenance

- **feat: `SourceReference` + `SourceQuote` models** — the publish-validated citation contract (`source_id`, `title`, `authority`, HTTPS `url`, `locator`, `source_version`, `source_date`, `content_digest`, `licence`, `verified_at`, verbatim `quote`, self-locating `deep_link`, `schema_version`), returned identically by both explanation surfaces. Unknown fields are preserved so the additive `schema_version` evolution cannot break a pinned consumer.
- **feat: `get_explanation(ruleset_id)` (sync + async) returning the typed `ExplainResponse`,** with resolved identity and typed references per criterion. `explain()` still returns the raw dict for existing callers.
- **feat: `DecideResponse.decision_explanation` + `.source_references()`** parse the `/decide` explanation into `DecisionExplanation`. Note the two surfaces differ: `/explain` returns a **flat** `criteria` array, `/decide` nests criteria under `explanation.groups[].criteria[]`. They share the DTO, not the envelope — the SDK models them separately and the tests assert the distinction.

### The two access boundaries are labelled

- **feat: `AethisError.boundary`** is `"evaluation"` or `"authoring"` on a 401/403, and the exception message now names which door was closed — no-key evaluation (`/decide`, `/rulesets`, `/schema`, `/explain`) versus invite-only authoring — plus the access-request URL. README and examples carry the same labelling before either path.

### Release integrity and hermetic install evidence

- **feat: `scripts/release_integrity.py`** emits the tuple a release candidate is pinned on — `(package, version)` → exact sdist/wheel sha256 → source commit/branch/clean-state — and re-verifies it against local files or against what PyPI actually serves. Wired into `publish.yml` before publication (`--require-clean`) and after (`--verify-registry`).
- **feat: `scripts/hermetic_install_check.py`** installs the exact artefact into a throwaway world — temporary `HOME`/`XDG_*`/cache, every `AETHIS_*` and provider key unset, empty cache on first install, no alternate index — then runs an offline smoke that parses captured engine payloads through the installed package, and a **poisoned-artefact negative control** that must fail. New `hermetic` CI job across ubuntu/macos × Python 3.11/3.12/3.13.
- **feat: `scripts/capture_engine_fixtures.py`** records the fixtures under `tests/fixtures/` from a live engine (anonymously, against a public showcase ruleset), including the engine's own JSON Schemas, so the mocked suite is tested against real wire payloads rather than hand-written approximations.
- **chore: Python 3.13 added to the classifiers and the CI matrix.** `jsonschema` added to the `dev` extra (test-only; the shipped package is still just `httpx` + `pydantic`).

### Review-wave fixes (same release)

- **fix: `get_source()` reported the wrong access boundary.** `/rulesets/{id}/source` sits under the `/public/rulesets` prefix but is key-required behind a scope external keys are not issued, so the prefix match labelled a 401 there `"evaluation"` and told the reader to go looking for a ruleset-visibility problem for a door that will never open. Key-required sub-paths are now excluded from the evaluation prefix, and both `get_source` docstrings say so. Prefer `get_explanation()`, which is anonymous on a public ruleset and returns the same `SourceReference` DTO.
- **fix: `content_digest` is validated against `^sha256:[0-9a-f]{64}$`.** `md5:…`, a truncated `sha256:beef`, non-hex, uppercase and bare-hex values now normalise to `None` rather than being carried into an audit record — the same "looks like a value, isn't" class as the `"unknown"` version.
- **fix: `--require-clean` passed vacuously when git provenance was unreadable.** `source_provenance()` returns `dirty: None` (unknown) when git cannot be read, and the gate tested it for falsiness — so with no `.git` the script exited 0 while recording `commit: null`. Provenance problems are now checked positively (`dirty is not False`, plus a missing commit in its own right).
- **fix: the poisoned-artefact control was vacuous on every CI runner.** It flipped the final byte, which lands in the end-of-central-directory comment field; strict zip readers reject it, lenient ones scan backwards and install happily. It is replaced by two controls: a **digest** control (a *valid, installable* substituted wheel that the real `verify_files` must reject — deterministic, and the layer that actually protects users) and an **installer** control (a wheel whose compressed stream is corrupted, asserted positively on `stage == "uv pip install"` plus stderr that names the corruption, rather than on the absence of one unrelated string).
- **fix: publication is gated on `--verify-files` immediately before the upload**, which is irreversible, in addition to the post-publish registry check.
- **fix: the README session loop no longer demonstrates the bug this release exists to prevent.** It looped on `next_question() is not None`; it now loops on `status()`, with a table of the four states that loop conflated.
- **fix: ruff's rule selection is pinned** (`ruff>=0.6.0,<0.17` plus an explicit `[tool.ruff.lint] select`). CI installed ruff unpinned, so 0.16.0's wider default turned the lint gate red on 61 errors — before pytest ran at all. Mirrors aethis-cli#90. CI also now lints `examples/`, which it had never covered.
- **fix: captured OpenAPI `examples` are stripped, and a test guards the fixtures.** The engine's `caller_ref` example named a real pilot firm, which a verbatim capture committed to this public repo. `examples` carry no structural information and validation ignores them, so they are no longer captured; a standing test fails on any internal tenant name or immigration term in `tests/fixtures/`.
- **test: the two invariants that no ordinary test could reach are now covered.** `is_terminal`'s blocking-error clause and `SessionStatus.is_complete`'s `not blocked` clause are each masked by the parse validator and the constructor invariant respectively — so deleting either left the suite green while removing the last guard on a bypass route. Both are now exercised through `model_construct` / `object.__setattr__` / `dataclasses.replace`, and verified to fail when the clause is removed.

## 0.10.0 (2026-07-21)

- **feat: `usage()` + `client.rate_limit` — rate-limit budget + headers.** New `Aethis.usage()` / `AsyncAethis.usage()` return a `UsageResponse` (per-operation-class `used`/`limit`/`remaining`/`reset` over the rolling 24h window + a 7/30-day rolling summary) from `GET /api/v1/public/usage`. Every response's `X-RateLimit-*` headers are now parsed onto `client.rate_limit` (a `RateLimit` model: `operation_class`/`limit`/`remaining`/`reset`), so a consuming app can read its remaining budget — especially `generate` (the scarce LLM class) — without a separate call. New models `UsageResponse`, `ClassUsage`, `RollingUsage`, `RateLimit`, all exported. (epic aethis-workspace#552)
- Requires aethis-core's `/usage` + `X-RateLimit-*` surface (epic #552 P2); the public release of this version is held until that is live on `api.aethis.ai`.
- **ci: cut a GitHub Release on publish.** The `publish` workflow now creates a GitHub Release for each just-published tag, using that version's `CHANGELOG.md` section as the release notes, so the "watch → releases" subscribe channel stays current automatically. Idempotent (create-or-skip on an existing Release) and `--verify-tag` (never mints a synthetic tag). No package/runtime change. (epic aethis-workspace#526)

## 0.9.0 (2026-07-17)
- **feat(models): `robot_hints` + `engine_version` on the rulebook schema; `engine_version` on the ruleset schema.** New `RulebookSchemaResponse` model (`rulebook_id`, `sections`, `fields`, `robot_hints`, `engine_version`) for `GET /api/v1/public/rulebooks/{id}/schema` — `robot_hints` is the rulebook's natural-language conversational-agent guidance keyed by beat (`general_context`, `preamble`, `session_start`, `postamble`, `session_end`, `stuck`), `None` for a rulebook authored before the field existed. `SchemaResponse` (ruleset schema) gains `engine_version: str | None = None` for parity, also back-compat (defaults `None` when the engine doesn't send it — true of the ruleset schema route today).
- **feat(models): `graph`/`GraphResponse` for the new `/graph` endpoint.** New `GraphResponse` (`ruleset_id`/`rulebook_id`, `slug`, `name`, `graph`, `mermaid`) and `RulesetGraph` (`nodes`, `edges`, `sections`, `stats`) model the ruleset/rulebook dependency graph (field → criterion → group → outcome) plus its rendered Mermaid diagram. Node/edge shape varies by node `type`, so nodes/edges stay loosely-typed dicts rather than a rigid per-type schema — deliberately permissive so a legacy or empty graph (`nodes: []`) still parses.
- **feat(client): `get_graph(ruleset_id)`** (sync + async) — wraps `GET /api/v1/public/rulesets/{id}/graph`, returning `GraphResponse`. Public rulesets can be inspected without an API key, same as `get_schema()`.
- **feat(decide): `include_graph_overlay` parameter on `decide()` / `decide_rulebook()`** (sync + async), and a matching `graph_overlay: dict[str, Any] | None = None` field on `DecideResponse`. Set `include_graph_overlay=True` to get this decision's per-criterion status stamped onto the ruleset's dependency graph, in the same shape `get_graph()` returns.
- All additions are additive and backwards-compatible: every new field defaults to `None`/`False`/an empty collection, so a legacy response (no `robot_hints`, no `engine_version`, no `graph_overlay`) still deserialises unchanged.

## 0.8.0 (2026-07-15)
- **feat(errors): typed 401/403/429 exceptions carrying the structured error envelope.** `classify_response` now raises `AethisAuthError` (401), `AethisPermissionError` (403), or `AethisRateLimitError` (429) — each a subclass of `AethisAPIError`, so existing `except AethisAPIError` handlers keep catching them (non-breaking). `AethisError` gains `.reason_code`, `.missing_permissions`, and `.hint`, lifted out of the public API's structured envelope (`{"detail": {"error", "reason_code", "missing_permissions", "hint", ...}}`), so a caller can branch on `err.reason_code == "denied_missing_permission"` or read `err.missing_permissions` without re-parsing `err.body`. Plain-string and FastAPI-422-list details are untouched (fields stay `None` / `[]`). Constructor stays backwards-compatible (new args default to `None`).
- **test(staging): live integration lane against `staging.api.aethis.ai`.** New `tests/integration/` (marker `staging`, excluded from the PR gate) mints a real API key the way a user does — Clerk sign-in ticket → frontend-API JWT → `POST /api/v1/keys/` → teardown — and exercises every public method on `Aethis` + `AsyncAethis` (decide, decide_rulebook, list_rulesets, get_schema, whoami, explain, explain_failure, get_source, sync/async session flows) plus live 401/403 typed-error assertions and a contract cross-check. Reports red (never green-by-skip) when creds are missing or staging/contract is unreachable.
- **test(parity): recorded-live fixture parity.** `tests/shapes.compare_shape` diffs the mocked `conftest` fixture builders (`make_decide_response`, `make_schema_response`, `make_ruleset_summary`) against real staging payloads so the mocked suite can't silently drift from reality; the builders were updated to match the current engine shape (`slug`/`rulebook_id`, `graph_overlay`/`timing`, richer `next_question`/schema fields).
- **chore(ci): coverage floor (`--cov-fail-under=45`) + `staging` marker + nightly `staging-integration.yml`** (report-only, `workflow_dispatch` + `schedule`, uploads a `qa-run-record` artifact for the `sdk-staging` lane). The coverage flags live in the CI command, not in `addopts`, so a bare `pytest` / `uv run pytest` works without `pytest-cov` (which is only in the `dev` extra) installed; the floor is still enforced in CI.

## 0.7.0 (2026-07-04)
- **fix(errors): attach the API's `detail` (and full `body`) to `AethisAPIError`.** On the primary error path, `classify_response` parsed the 4xx `detail` only to log it, then raised `AethisAPIError("Aethis API returned 422")` — blinding callers to *why* the request failed. The exception message now reads `"Aethis API returned 422: <detail>"` when a detail is present, and `AethisError` gained `.detail` / `.body` attributes carrying the parsed payload (both `None` for timeouts / connection errors). Constructor signatures stay backwards-compatible (new args default to `None`).
- **fix(models): `DecideResponse.explanation` is a single object, not a list.** The field was typed `list[dict] | None` but the engine returns `Optional[Dict[str, Any]]` (`{decision, groups: [...], unused_facts: [...]}`), a latent `ValidationError` for any caller that actually requested one. Retyped to `dict[str, Any] | None`.
- **feat(decide): `include_explanation` parameter on `decide()` / `decide_rulebook()`** (sync + async). The engine has always accepted `include_explanation` on `POST /decide`, but the SDK never sent it, leaving `DecideResponse.explanation` permanently `None`. Passed through in the request payload alongside `include_trace`; defaults to `False`.
- **feat(models): typed `FieldNote` and `NextQuestion.notes`.** The engine attaches structured author guidance (`note_text`, `source`, `metadata`) to each `next_question`; the SDK silently dropped it. Adds the `FieldNote` model (exported from the package) and `notes: list[FieldNote]` on `NextQuestion`, defaulting to `[]` so older responses without notes keep parsing.
- **feat(client): `list_rulesets(limit=20, offset=0)`** (sync + async) — wraps `GET /api/v1/public/rulesets`, returning the previously-exported-but-unreachable `RulesetSummary` model. Anonymous callers get public rulesets; an API key additionally surfaces that key's own rulesets. `limit` is clamped by the engine to 1-50.
- **docs(readme, `_base`): capability-table + docstring fixes.** README's "What's included" table now lists `explain_failure`, `decide_rulebook`, `list_rulesets`, `include_explanation`, and `FieldNote`; the `build_headers` docstring no longer names a nonexistent `/next_question` endpoint.

## 0.6.0 (2026-05-25)
- **feat(explain-failure): `Aethis.explain_failure()` + `AsyncAethis.explain_failure()`** — wraps `POST /api/v1/public/rulesets/{ruleset_id}/explain-failure`, returning the failing criterion and a targeted fix hint for a mismatched `/decide` result. Accepts `field_values`, `expected_outcome` (`"eligible"` | `"not_eligible"` | `"undetermined"`), and an optional `test_name` (default `"test"`). Return type is `dict[str, Any]` to match `explain()` / `get_source()` — can be tightened once the response shape stabilises. Note: `ruleset_id` must be the concrete identifier (not a slug); the underlying endpoint does not currently resolve slugs. Previously, callers had to drop to raw `httpx` for this endpoint — flagged in `recipes/evaluate-a-case.mdx` and `recipes/debug-a-decide.mdx`.

## 0.5.1 (2026-05-22)
- **docs(readme): rulebook surface advertised on the PyPI landing page.** The v0.5.0 release shipped `decide_rulebook()` and `rulebook_id` on `DecideResponse`, but the README still framed the SDK as ruleset-only. Adds a dedicated "Composed rulebook" section with a runnable UK FSM example, the always-scope-gated note, and the async equivalent.
- **docs(install): switch `pip install` to `uv add` per workspace no-pip rule.** The PyPI landing page is a public-facing surface bound by `.claude/rules/no-pip.md`. Adds `uv pip install` as a venv-friendly alternative.
- **docs(engine_version): update sample audit-field comment from `aethis-core@0.10.0` to `aethis-core@0.27.0`** — matches live prod engine.
- **docs(beta): clarify that decision endpoints are anonymous only for single rulesets** — rulebook decide is always scope-gated, so the SDK's "anonymous when no key" claim needed a footnote.

## 0.5.0 (2026-05-22)
- **feat(rulebook): `Aethis.decide_rulebook()` + `AsyncAethis.decide_rulebook()`** — evaluate a composed multi-ruleset rulebook through the SDK. Mirrors `decide()` but sends `rulebook_id` in the payload. Accepts either an opaque `rb_<id>` or a slug (e.g. `aethis/uk-fsm`). Requires an API key — rulebook evaluation is always scope-gated. Closes [#14](https://github.com/Aethis-ai/aethis-sdk-python/issues/14). Requires aethis-core v0.27.0+ live on the target API for slug-form rulebook paths.
- **feat(models): add `rulebook_id: Optional[str]` to `DecideResponse`** — surfaces the rulebook identifier when the response was a composed-rulebook decide. Backwards-compatible: ruleset-only decides keep `rulebook_id=None`.

## 0.4.6 (2026-05-20)
- feat(models): add `name: Optional[str]` to ruleset response models — surfaces the human-readable section name introduced in aethis-core v0.18.0. Adds `RulesetSummary` (anonymous catalogue / `GET /api/v1/public/rulesets`) and `RulesetListItem` (project-scoped / `GET /api/v1/public/projects/{id}/rulesets`) as typed models, and adds the same `name` field to `SchemaResponse`. Backwards-compatible: pre-backfill rulesets serialise with `name=None`.

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
