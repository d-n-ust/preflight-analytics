"""The collision detector: compare every governed definition against every other and report the
confusable pairs that resolve to different numbers, clustered per concept, most dangerous first.

The public entry point is `detect_collisions`. It is a composition of small pure functions —
`partition`, `classify`, the edge builders, `_cluster`, `rank` — each of which takes its inputs and
returns a value with no shared state. That structure is deliberate: every stage is testable in
isolation, and the pairwise work is embarrassingly parallel because nothing mutates.

Similarity decides only which name-pairs are worth examining (the confusability gate); danger is
decided structurally by `classify`, never by similarity.

Types: DUPLICATE, SCOPE_TRAP, SIBLING, CONCEPT_FORK, DEFINITION_DIVERGENCE, NAME_COLLISION,
GRAIN_MISMATCH, VERSIONED_TWIN.
"""

from __future__ import annotations

import itertools
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import NamedTuple

from .gate import make_gate
from .model import (
    DANGER_RANK,
    DEFAULT_CONFIG,
    Classification,
    CollisionType,
    Danger,
    DetectConfig,
    Finding,
    GroundingFact,
    Item,
)
from .scope import is_subset, scope_equal, subsumes

Similarity = Callable[[GroundingFact, GroundingFact], float]

_ID = re.compile(r"[a-z_][a-z0-9_]{2,}")
_TECH = {"id", "raw_payload", "tags", "currency", "zip", "phone", "handle", "referrer",
         "landing_page", "anonymous_id"}


class Edge(NamedTuple):
    """A classified pair, keyed by fact ids — the input to clustering."""

    cls: Classification
    a: str
    b: str


# ── predicates on a single fact / pair ───────────────────────────────────────────────────────────
def is_plumbing(label: str) -> bool:
    """Drop by ROLE, not by a hand list: surrogate keys, timestamps, and pure technical columns.
    Keeps business keys (`customer_id` vs `user_id` is a real collision) and `email` (a real rename)."""
    lbl = label.lower()
    return lbl in _TECH or lbl.endswith("_key") or lbl.endswith("_at")


def _cols(s: str | None) -> set[str]:
    return set(_ID.findall(s.lower())) if s else set()


def _meaning_agrees(a: GroundingFact, b: GroundingFact, min_shared: int) -> bool:
    """Same measure: at least `min_shared` co-declared meaning facets, and all co-declared agree."""
    facets = ("entity", "agg", "base", "measure")
    shared = [f for f in facets if a.meaning[f] is not None and b.meaning[f] is not None]
    return len(shared) >= min_shared and all(a.meaning[f] == b.meaning[f] for f in shared)


def _norm_label(label: str) -> str:
    """Fold a label to its bare identity: lowercase, separators removed. So a prose doc heading
    ('value moment') and the metric it documents ('value_moments') count as the SAME term — one
    written in words, one in code — rather than two names that merely read alike."""
    return re.sub(r"[^a-z0-9]+", "", label.lower())


def classify(a: GroundingFact, b: GroundingFact, sim: float,
             config: DetectConfig = DEFAULT_CONFIG) -> Classification | None:
    """Classify one pair into a collision type + danger, or None. Divergence is asserted only with
    evidence. `sim` is the pair's confusability score, used only by the read-alike name rule."""
    cross = a.layer != b.layer
    exact = _norm_label(a.label) == _norm_label(b.label)

    # 1. same measure (>= min_shared_facets co-declared meaning facets, all agree)
    if _meaning_agrees(a, b, config.min_shared_facets):
        if scope_equal(a.scope, b.scope):
            if a.grain == b.grain:
                return Classification("DUPLICATE", "low", "same measure, scope and grain under two names")
            # same population, different grain — a semi-/non-additive measure cannot be rolled up
            add = a.additive or b.additive
            danger: Danger = "high" if add in ("semi", "non") else "medium"
            return Classification("GRAIN_MISMATCH", danger,
                f"same measure and population at different grain ('{a.grain}' vs '{b.grain}'); "
                f"the measure is {add or 'additive'}"
                + (" and cannot be summed across that grain" if add in ("semi", "non") else ""))
        if subsumes(a.scope, b.scope):
            narrow, wide = (a, b) if is_subset(a.scope, b.scope) else (b, a)
            return Classification("SCOPE_TRAP", "high",
                f"same measure; '{narrow.label}' is '{wide.label}' plus a filter — bare question "
                f"silently scoped, swap invisible")
        return Classification("SIBLING", "low", "same measure, incomparable scopes — a question must name one")

    # 2. fact twin: the same column counted the same way over two grains of one process.
    if _fact_twin_candidate(a, b):
        add = a.additive or b.additive
        danger = "high" if add in ("semi", "non") else "medium"
        return Classification("FACT_TWIN", danger,
            f"same measure counted over '{a.base}' and '{b.base}' — one process at two grains; "
            f"a bare question resolves to two different numbers and neither name says which")

    # 3. concept fork: same entity+agg+table, DIFFERENT measured column/expr (the revenue family).
    # Exception: a distinct count of an entity KEY counts that entity, so two different keys
    # (count_distinct(customer_id) vs count_distinct(location_id)) are two named entities, not one
    # forked concept — the differing name is the disambiguator, not a hidden qualifier of a shared
    # concept. Those two measures also read alike enough to pass the gate ("*_with_orders"), so
    # without this the pair reads as a fork it is not.
    if (a.entity and a.entity == b.entity and a.agg == b.agg and a.base and a.base == b.base
            and a.measure and b.measure and a.measure != b.measure
            and not (a.agg == "count_distinct" and _is_key(str(a.measure)) and _is_key(str(b.measure)))):
        return Classification("CONCEPT_FORK", "high",
            "same entity/table aggregated the same way over different columns — a bare concept "
            "resolves to different numbers")

    # 3. same term, two prose definitions that differ
    if exact and a.layer == "docs" and b.layer == "docs":
        ta, tb = set(a.text.lower().split()), set(b.text.lower().split())
        j = len(ta & tb) / len(ta | tb) if ta and tb else 1.0
        if j < config.definition_overlap:
            return Classification("DEFINITION_DIVERGENCE", "high", f"'{a.label}' documented two different ways")
        return None

    # 4. same term across layers with comparable scope that conflicts
    if exact and cross and a.scope and b.scope and set(a.scope) != set(b.scope):
        return Classification("DEFINITION_DIVERGENCE", "high",
            f"'{a.label}' resolves to a different scope in {a.layer} vs {b.layer}")

    # 5. same term across layers, one side prose — flag only if the doc omits the modelled columns.
    #    Keys don't count: a business dictionary won't cite `user_id` for a count-distinct-of-users,
    #    so a metric measured on a key raises no divergence from prose that omits it.
    if exact and cross:
        sl, dc = (a, b) if a.measure else (b, a)
        cols = {c for c in _cols(sl.measure) if not _is_key(c)}
        if cols and dc.text and not (cols & _cols(dc.text)):
            return Classification("DEFINITION_DIVERGENCE", "medium",
                f"'{a.label}' is modelled on {sorted(cols)} but its documentation does not "
                f"reference those columns")
        return None

    # 6. same term, same layer, different measure -> overloaded name
    if exact:
        return Classification("NAME_COLLISION", "medium", f"two different '{a.label}' in the {a.layer} layer")

    # 7. near-identical names, different things. NAME_COLLISION is also produced outside classify:
    # _warehouse_synonym_edges (read-alike warehouse columns) and _overloaded_column_findings (one
    # column name spread across many tables) — the three are the places to look for this type.
    if sim >= config.name_collision:
        return Classification("NAME_COLLISION", "low", f"'{a.label}' and '{b.label}' read alike, different things")
    return None


# ── stages ───────────────────────────────────────────────────────────────────────────────────────
def partition(facts: list[GroundingFact]) -> tuple[list[GroundingFact], list[GroundingFact]]:
    """Split facts into (primary, warehouse). Primary = the grounding surface an agent queries on
    (semantic + welded queries + docs); warehouse = raw structure, compared more conservatively."""
    primary = [f for f in facts
               if (f.layer in ("semantic", "queries") and f.kind in ("metric", "segment", "dimension", "query"))
               or f.layer == "docs"]
    warehouse = [f for f in facts if f.layer == "warehouse"]
    return primary, warehouse


_MODEL_PREFIX = re.compile(r"^(?:fct|fact|f|dim|d|agg|stg|int|mart|rpt)_")


def _process_stem(table: str) -> str:
    """A table name reduced to the business process it describes: modelling prefix dropped, plural
    folded. `fct_subscriptions` and `fct_subscription_months` both start from `subscription`."""
    s = _MODEL_PREFIX.sub("", table.lower())
    return s[:-1] if s.endswith("s") else s


def _same_process(a: str, b: str) -> bool:
    """Whether two tables describe the same business process — the test that separates a real fact
    twin from two unrelated facts.

    A periodic snapshot is conventionally named for the fact it snapshots plus its grain
    (`fct_subscriptions` -> `fct_subscription_months`), so one stem prefixes the other. Activity
    and subscriptions share no stem, which is exactly the pair that must stay silent: counting
    users over a product-activity fact and over a subscription snapshot are two different
    questions, not one question answered twice."""
    x, y = _process_stem(a), _process_stem(b)
    if x == y:
        return True
    short, long = (x, y) if len(x) <= len(y) else (y, x)
    return len(short) >= 4 and long.startswith(short)


def _fact_twin_candidate(a: GroundingFact, b: GroundingFact) -> bool:
    """The same count, taken over two grains of one business process.

    Two metrics aggregate the same column the same way, but read from different tables that
    describe the same process — a transaction fact and its own periodic snapshot. The numbers
    differ by construction (a lifetime count is not a current count) and neither name says which
    grain it speaks for.

    Like `_same_meaning_candidate`, this bypasses the similarity gate, and for the same reason at a
    different angle: the gate starves on synonyms. Measured on a real layer, `subscribers` scored
    0.377 against `paying_users` while `active_users` scored 0.490 against it — the dangerous pair
    below the harmless one, so any name-gated version of this rule would flag the wrong pair first.
    The structure is the evidence; the name is not evidence either way."""
    if a.kind != "metric" or b.kind != "metric":
        return False
    if not a.agg or a.agg != b.agg or not a.measure or a.measure != b.measure:
        return False
    table_a, table_b = a.base, b.base
    if not table_a or not table_b or table_a == table_b:
        return False
    return _same_process(table_a, table_b)


def _same_meaning_candidate(a: GroundingFact, b: GroundingFact, config: DetectConfig) -> bool:
    """A pair whose DECLARED meaning already agrees is examined regardless of name similarity.

    The similarity gate exists to prune text comparisons across unrelated pairs; it is a heuristic,
    not evidence. When two facts wrap the same measure, or agree on every meaning facet they both
    declare, the structure alone proves they are the same computation under two names — and names
    prove nothing either way (`mrr` vs `monthly_recurring_revenue` share a measure and three
    letters, so an acronym starves any text gate). Only meaning-agreement bypasses the gate: the
    CONCEPT_FORK rule (same table, different columns) still requires the gate's name evidence,
    because without it `order_total` vs `tax_paid` would read as a fork of one concept.

    Restricted to metric-kind pairs: metrics are the surface an agent selects from, and metric
    aliasing is the failure this catches. A dimension legitimately mirrors a column a metric wraps,
    so letting dimensions bypass the gate would flag routine modelling as duplication."""
    if a.kind != "metric" or b.kind != "metric":
        return False
    return ((a.measure is not None and a.measure == b.measure)
            or _meaning_agrees(a, b, config.min_shared_facets))


def _primary_edges(primary: list[GroundingFact], similarity: Similarity, config: DetectConfig) -> list[Edge]:
    edges: list[Edge] = []
    for a, b in itertools.combinations(primary, 2):
        if is_plumbing(a.label) or is_plumbing(b.label):
            continue
        s = similarity(a, b)
        if (a.label != b.label and s < config.gate
                and not _same_meaning_candidate(a, b, config)
                and not _fact_twin_candidate(a, b)):
            continue
        c = classify(a, b, s, config)
        if c is not None:
            edges.append(Edge(c, a.id, b.id))
    return edges


def _warehouse_label_edges(primary: list[GroundingFact], warehouse: list[GroundingFact],
                           config: DetectConfig) -> list[Edge]:
    """A primary fact and a warehouse fact sharing a label are an exact-name cross-layer pair."""
    wh_by_label: dict[str, list[GroundingFact]] = defaultdict(list)
    for f in warehouse:
        if not is_plumbing(f.label):
            wh_by_label[f.label].append(f)
    edges: list[Edge] = []
    for p in primary:
        for w in wh_by_label.get(p.label, []):
            c = classify(p, w, 1.0, config)
            if c is not None:
                edges.append(Edge(c, p.id, w.id))
    return edges


def _warehouse_synonym_edges(warehouse: list[GroundingFact], similarity: Similarity,
                             config: DetectConfig) -> list[Edge]:
    """Warehouse columns whose names read alike (on_hand ~ qty_on_hand): likely one thing under two
    names, or two under alike names. One representative per label keeps this near-linear."""
    seen: dict[str, GroundingFact] = {}
    for f in warehouse:
        if f.kind == "column" and not is_plumbing(f.label) and f.label not in seen:
            seen[f.label] = f
    edges: list[Edge] = []
    for a, b in itertools.combinations(seen.values(), 2):
        if a.label == b.label or similarity(a, b) < config.warehouse_synonym:
            continue
        note = (f"warehouse columns '{a.label}' and '{b.label}' read alike — likely the same "
                f"thing under two names, or two things under alike names")
        edges.append(Edge(Classification("NAME_COLLISION", "low", note), a.id, b.id))
    return edges


def _is_key(label: str) -> bool:
    """A join / surrogate key: `id` or a `<entity>_id` foreign key. The same key appearing across a
    star's fact tables is expected wiring, not an overloaded meaning, so it is excluded from the
    overload check. It stays visible to the near-synonym check, where `user_id` vs `customer_id` is a
    real rename collision."""
    lbl = label.lower()
    return lbl == "id" or lbl.endswith("_id")


def _overloaded_column_findings(warehouse: list[GroundingFact], config: DetectConfig) -> list[Finding]:
    """A non-key column name that appears in many tables may mean different things in each. Cite one
    line per table (the column's own line in each) rather than a single synthetic item, so the reader
    sees exactly where each occurrence is."""
    occ: dict[str, list[GroundingFact]] = defaultdict(list)
    for f in warehouse:
        if f.kind == "column" and not is_plumbing(f.label) and not _is_key(f.label):
            occ[f.label].append(f)
    out: list[Finding] = []
    for label, facts in sorted(occ.items()):
        by_table: dict[str | None, GroundingFact] = {}
        for f in facts:
            by_table.setdefault(f.base, f)       # first occurrence in each table
        if len(by_table) >= config.overloaded_tables:
            items = tuple(Item(f.id, f.label, f.layer, f.source) for f in by_table.values())
            out.append(Finding("NAME_COLLISION", "medium",
                f"column '{label}' in {len(by_table)} tables — meaning may differ", items))
    return out


# A trailing token that marks a versioned or leftover twin rather than a different concept.
# Strict on purpose: `orders_daily` is a different grain, not a version, so grain-ish suffixes are
# NOT here. Date stamps (users_2025, subscriptions_backup_2026_03) count as leftovers.
_VERSION_SUFFIX = re.compile(
    r"(?:_v\d+|_old|_new|_bak|_backup.*|_tmp|_temp|_copy|_final|_legacy|_deprecated|_archive.*"
    r"|_(?:19|20)\d{2}(?:_\d{2}){0,2})$")


def _version_twin_findings(facts: list[GroundingFact], config: DetectConfig) -> list[Finding]:
    """`users` next to `users_v2`: the suffix says one is a version or leftover of the other, and
    nothing marks which one is current. This is written ambiguity in its purest form — the whole
    signal is in the names — yet a similarity gate can miss it (`users` ~ `users_v2` scores below
    the synonym threshold). So it is matched exactly: strip a conventional version/leftover suffix
    and look for a fact with the bare name, same layer and kind."""
    by_key: dict[tuple[str, str, str], GroundingFact] = {}
    for f in facts:
        if not is_plumbing(f.label):
            by_key.setdefault((f.layer, f.kind, f.label), f)
    out: list[Finding] = []
    for (layer, kind, label), f in sorted(by_key.items()):
        stripped = _VERSION_SUFFIX.sub("", label)
        if stripped == label or not stripped:
            continue
        base = by_key.get((layer, kind, stripped))
        if base is None:
            continue
        out.append(Finding("VERSIONED_TWIN", "medium",
            f"'{label}' reads as a versioned or leftover twin of '{stripped}' — nothing marks "
            f"which one is current",
            (Item(base.id, base.label, base.layer, base.source),
             Item(f.id, f.label, f.layer, f.source))))
    return out


class _UnionFind:
    """Disjoint-set with path compression. An implementation detail of clustering; the function that
    uses it (`_cluster`) is pure — same edges in, same findings out."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self._parent[self.find(a)] = self.find(b)


def _cluster(edges: list[Edge], by_id: dict[str, GroundingFact]) -> list[Finding]:
    """Group edges into per-concept findings: within each collision type, connected components become
    one finding, carrying the most dangerous edge's danger and note."""
    by_type: dict[CollisionType, list[Edge]] = defaultdict(list)
    for e in edges:
        by_type[e.cls.type].append(e)

    findings: list[Finding] = []
    for ctype, group in by_type.items():
        uf = _UnionFind()
        for e in group:
            uf.union(e.a, e.b)
        members: dict[str, set[str]] = defaultdict(set)
        worst: dict[str, Classification] = {}
        for e in group:
            root = uf.find(e.a)
            members[root] |= {e.a, e.b}
            cur = worst.get(root)
            if cur is None or DANGER_RANK[e.cls.danger] < DANGER_RANK[cur.danger]:
                worst[root] = e.cls
        for root, ids in members.items():
            items = tuple(
                Item(i, by_id[i].label, by_id[i].layer, by_id[i].source) for i in sorted(ids))
            c = worst[root]
            findings.append(Finding(ctype, c.danger, c.note, items))
    return findings


def rank(findings: list[Finding]) -> list[Finding]:
    """Most dangerous first; then by type; then larger clusters first."""
    return sorted(findings, key=lambda f: (DANGER_RANK[f.danger], f.type, -len(f.items)))


def detect_collisions(facts: Iterable[GroundingFact], *, gate: str = "auto", model=None,
                      config: DetectConfig | None = None) -> list[Finding]:
    """Detect confusable grounding facts across the whole surface, most dangerous first.

    `gate` selects the confusability gate: "auto" uses embeddings when installed and falls back to a
    dependency-free lexical gate; "lexical" forces the fallback; "embeddings" requires the optional
    extra. Pass any object with `.encode` as `model` to reuse one instance. `config` overrides
    detector thresholds.

    Complexity: the primary-vs-primary pass is O(n^2) in the number of semantic facts (every pair is
    scored by the gate). This is comfortable into the low thousands of metrics; it is not pruned by a
    blocking prefilter on purpose, because a lexical prefilter would defeat the embedding gate's whole
    value — catching non-lexical synonyms (revenue ~ sales) that share no characters. The warehouse
    passes are indexed and near-linear. If you point this at a layer with many thousands of metrics
    and it is slow, that is the place to add an approximate-nearest-neighbour index over the label
    embeddings, not a character prefilter."""
    config = config or DEFAULT_CONFIG
    facts = list(facts)
    by_id = {f.id: f for f in facts}
    primary, warehouse = partition(facts)
    sim, _gate_name = make_gate([f.label for f in primary + warehouse], kind=gate, model=model)

    def similarity(a: GroundingFact, b: GroundingFact) -> float:
        return sim(a.label, b.label)

    edges = (_primary_edges(primary, similarity, config)
             + _warehouse_label_edges(primary, warehouse, config)
             + _warehouse_synonym_edges(warehouse, similarity, config))
    findings = (_cluster(edges, by_id) + _overloaded_column_findings(warehouse, config)
                + _version_twin_findings(facts, config))
    return rank(findings)
