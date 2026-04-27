# Changelog

All notable changes to `aethis-sdk` will be documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.2.0 (2026-04-27)

### Added
- `DecideResponse.slug` — stable, human-readable handle for the bundle
  (e.g. `aethis/uk-fsm/child-eligibility`). Set when the resolved bundle
  was published under a slug; `None` otherwise. Prefer this over
  `bundle_id` for any reference that should survive bundle regeneration.
- `SchemaResponse.slug` — same handle, surfaced from
  `GET /bundles/{id}/schema`.

### Notes
- Backwards-compatible. Existing code that reads `bundle_id` keeps
  working unchanged; `slug` is purely additive.
- Requires the `aethis-core` engine release that surfaces the field in
  `/decide` and `/bundles/{id}/schema` responses (rolling out 2026-04).
  Older engines will simply leave `slug=None`.

## 0.1.0 (initial)

- Sync + async clients (`Aethis`, `AsyncAethis`) for `/decide`,
  `/bundles/{id}/schema`, `/me`, `/bundles/{id}/explain`,
  `/bundles/{id}/source`.
- Stateful decision adapters (`SyncDecisionSession`, `DecisionSession`).
- Pydantic response models, exception hierarchy
  (`AethisError`, `AethisAPIError`, `AethisUnavailable`,
  `AethisTimeout`).
