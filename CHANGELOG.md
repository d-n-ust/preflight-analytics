# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims for
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] — 2026-08-18

Initial release.

### Added
- Static, cross-layer ambiguity detection across a dbt project's semantic layer, warehouse, and docs,
  with every finding cited to its source `.yml`/`.sql` line.
- Dialects: `dbt-manifest` (a whole dbt project via `target/manifest.json`), `metricflow` (raw
  MetricFlow YAML), `dbt` (raw model SQL), `cube` (Cube YAML/JS), and the native `env` layout.
- Seven finding types — `SCOPE_TRAP`, `CONCEPT_FORK`, `GRAIN_MISMATCH`, `DEFINITION_DIVERGENCE`,
  `NAME_COLLISION`, `DUPLICATE`, `SIBLING` — each with a worked example and recommended fix in the
  catalog.
- Confusability gate: a dependency-free lexical gate (default) or an optional embedding gate
  (`[embeddings]` extra).
- `preflight scan` CLI, a library API (`scan`, `detect_collisions`, `DetectConfig`), a composite
  GitHub Action, and a pre-commit hook.

[Unreleased]: https://github.com/d-n-ust/preflight-analytics/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/d-n-ust/preflight-analytics/releases/tag/v0.1.0
