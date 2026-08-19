# preflight on Cube — quickstart

preflight reads a [Cube](https://cube.dev) data model and flags the definitions that read alike but
resolve to different numbers — before an agent or a BI user grounds a question on the wrong measure.
Unlike dbt, **there is no build step**: a Cube model *is* its source files, so preflight reads them
directly. Point it at your model directory and scan.

    preflight scan path/to/cube/model --dialect cube

It handles both Cube formats: the YAML model (`cubes:` with `measures` / `dimensions` / `segments`)
and the classic JavaScript form (`cube('Name', { measures: … })`).

## Install

The distribution is `preflight-analytics` (the bare `preflight` name is taken on PyPI); the import and
CLI command stay `preflight`. Install with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install preflight-analytics   # or: pip install preflight-analytics
```

## A worked example (a real public Cube model)

Any repo with a Cube model works. This one is a published semantic-layer demo:

```bash
git clone --depth 1 https://github.com/xuanagi/semantic-native-nlq-demo
cd semantic-native-nlq-demo/cube/model

preflight scan . --dialect cube
```

```text
9 findings — high 5, medium 1, low 3

HIGH (5)
  opportunity_scores.yml:30: [CONCEPT_FORK] contentOpportunityScoreAvg[sem] ~ overallOpportunityScoreAvg[sem] ~ priceOpportunityScoreAvg[sem]
      same entity/table aggregated the same way over different columns — a bare concept resolves to different numbers
  ...
  model_scores.yml:11: [NAME_COLLISION] rowCount[sem] ~ rowCount[sem]
      two different 'rowCount' in the semantic layer
```

Two real confusions in a model nobody built as a trap:

- **`contentOpportunityScoreAvg` ~ `overallOpportunityScoreAvg` ~ `priceOpportunityScoreAvg`** — three
  "opportunity score" averages on one cube, differing only in which column is averaged. Ask for "the
  opportunity score" and you get three different numbers.
- **`rowCount` ~ `rowCount`** — two unrelated `rowCount` measures in different cubes. An agent that
  learned `rowCount` from one cube reads it wrong on the other.

Add `--detail` to print every colliding site with its `file:line` and the offending `- name:` line:

```bash
preflight scan . --dialect cube --detail
```

## Reading the output

`[sem]` is a Cube measure or dimension. Each finding is one of seven types; a worked example and the
recommended fix for every one is in **[catalog.md](catalog.md)**. The two above are the Cube analogues
of the dbt `food_revenue` fork and a reused column name — the same mistakes, one ecosystem over.

Severity is preflight's estimate of how likely the confusion is to bite at query time. Start with HIGH.

## What preflight reads from a Cube model

| Cube concept | preflight sees it as |
|---|---|
| a `cube` | the base / entity |
| a `measure` (its `type` + `sql`) | a metric — the aggregation and the measured column |
| a `dimension` | a grouping / grain |
| a `segment` (a named, reusable filter) | the population (scope) |

So the same cross-layer detector runs over Cube, and a scope baked into a measure's `sql` (a
`CASE WHEN …`) instead of a `segment` shows up as a `CONCEPT_FORK` or `SCOPE_TRAP`, just as it does in
dbt.

## On your own Cube project

Point it at wherever your cubes live (a directory is scanned recursively for `.yml`/`.yaml`/`.js`):

```bash
preflight scan path/to/model --dialect cube --detail
```

## Gate it in CI

```bash
preflight scan path/to/model --dialect cube --fail-on high   # non-zero exit on a HIGH finding
```

No database and no Cube build required — it reads the model files. See [ci.md](ci.md) for the GitHub
Action and pre-commit hook.
