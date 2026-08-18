# Contributing

Thanks for looking. preflight is a linter for *meaning* in an analytics layer — it finds definitions
that read alike but resolve to different numbers. Bug reports (especially a false positive or a missed
collision), new dialects, and new finding types are all welcome.

## Develop

The package is outside any workspace and uses [uv](https://docs.astral.sh/uv/):

```bash
uv sync --group dev          # core + dev tools (no torch)
uv run ruff check src tests  # lint
uv run mypy src/preflight    # type-check
uv run pytest -q             # test
```

CI runs exactly those three across Python 3.11–3.13. A pre-commit config is included
(`pre-commit install` to enable ruff + mypy locally). The formatter is deliberately not enforced — the
source is hand-aligned for readability.

## How it's built

Pure functions over frozen values, I/O at the edges. Read [`docs/library.md`](docs/library.md) for the
module map; the short version:

| module | job |
|---|---|
| `model.py` | immutable value types (`GroundingFact`, `Finding`, `DetectConfig`, …) |
| `scope.py` | population algebra — parse a filter into predicates, compare populations |
| `gate.py` | the confusability gate (lexical, or optional embeddings) |
| `adapters.py` + `metricflow.py` / `dbt_manifest.py` / `dbt_sql.py` / `cube.py` | dialects → `GroundingFact`s |
| `detect.py` | `classify` one pair, build edges, cluster, rank |

## Extending it

- **A new dialect** (e.g. LookML): add a loader that reads the artifact and returns
  `list[GroundingFact]`, then register it in `cli.py`'s `_LOADERS`. The detector is unchanged — a
  dialect is just an adapter.
- **A new finding type**: add a branch to `classify()` in `detect.py`, a member to `CollisionType` in
  `model.py`, and a worked example + fix to [`docs/catalog.md`](docs/catalog.md).

## Pull requests

Keep the three checks green, add a test that fails without your change, and match the surrounding style
— comments explain the *why*, names do the rest. Small, focused PRs merge fastest.
