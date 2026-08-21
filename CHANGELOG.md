# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims for
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.0] — 2026-08-21

### Added
- **`FACT_TWIN`**, a ninth finding type: the same column counted the same way over two grains of
  one business process — a transaction fact beside its own periodic snapshot. `subscribers` over
  `fct_subscriptions` and `paying_users` over `fct_subscription_months` return different numbers by
  construction, and neither name says which grain it speaks for. Like the 0.2.0 structural pairing,
  this bypasses the similarity gate, for the same reason at a different angle: the gate starves on
  synonyms. Measured on a real layer, `subscribers` scored 0.377 against `paying_users` while
  `active_users` scored 0.490 against it, so any name-gated version of the rule would flag the
  harmless pair first. Two tables count as one process when their names reduce to the same stem
  (`fct_subscriptions` -> `fct_subscription_months`), which is what keeps activity and subscription
  facts apart. Validated as a no-op on `dbt-labs/jaffle-shop`, `dbt-labs/jaffle-sl-template`, and
  four public Cube models.

### Fixed
- The MetricFlow adapter read a semantic model's table only from the dbt project form
  (`model: ref(...)`), not from the standalone form (`node_relation: {alias: ...}`), so every metric
  in a standalone layer carried no source table. `base` is a meaning facet, so its absence quietly
  weakened every rule that compares where two metrics read from.

## [0.3.0] — 2026-08-20

### Added
- **`VERSIONED_TWIN`**, an eighth finding type. `users` beside `users_v2`, or a table with a
  `_backup`/`_old`/date-stamped suffix beside its base name, is written ambiguity in its purest
  form: the whole signal is in the names, yet a similarity gate can score the pair below the
  synonym threshold and miss it. Matched exactly instead: strip a conventional version/leftover
  suffix and look for the bare name in the same layer and kind. Grain-style suffixes
  (`orders_daily`) are deliberately not matched. Validated as a no-op on `dbt-labs/jaffle-shop`,
  `dbt-labs/jaffle-sl-template`, and a public Cube model.


## [0.2.0] — 2026-08-19

### Added
- **Structural pairing.** Two metrics whose declared meaning already agrees — the same measure, or
  agreement on every meaning facet both declare — are now compared regardless of name similarity.
  The confusability gate is a pruning heuristic, not evidence, and it starves on acronyms: `mrr` vs
  `monthly_recurring_revenue` share a measure and three letters, so no text gate can pair them. Such
  pairs now reach the structural classifier unconditionally. The `CONCEPT_FORK` rule (same table,
  same aggregation, different columns) deliberately keeps its name-evidence requirement, because
  without it `order_total` vs `tax_paid` would read as a fork of one concept. Restricted to
  metric-kind facts; validated as a no-op on `dbt-labs/jaffle-shop`, `dbt-labs/jaffle-sl-template`,
  and a public Cube model, while catching previously missed metric aliases and scope traps on
  sprawled layers.

### Fixed
- Cube dialect now cites each finding to its source `file:line`, matching the dbt and `env` dialects.
  `load_cube` attaches a `Source` via `line_of_definition`, so `--detail` and JSON output carry the
  path and line for Cube models too.
- Documentation quoted finding counts from embeddings-gate runs; the counts a default (lexical)
  install reports are now quoted instead: 14 findings on `jaffle-sl-template`, 9 on the Cube demo.

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

[Unreleased]: https://github.com/d-n-ust/preflight-analytics/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/d-n-ust/preflight-analytics/releases/tag/v0.4.0
[0.3.0]: https://github.com/d-n-ust/preflight-analytics/releases/tag/v0.3.0
[0.2.0]: https://github.com/d-n-ust/preflight-analytics/releases/tag/v0.2.0
[0.1.0]: https://github.com/d-n-ust/preflight-analytics/releases/tag/v0.1.0
