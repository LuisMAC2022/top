"""Survey, clusters and transparent ranking.

Ranks candidates for human reading. It does not pronounce scholarly quality,
and it never lets a graph metric stand in for having read the paper. Every
dimension is reported separately; a combined score exists only if weights are
published in config/ranking.json, and it always ships with a sensitivity table.
"""

from __future__ import annotations

import dataclasses
import math
import re
from collections import defaultdict

from . import references, util

TOKEN = re.compile(r"[a-z][a-z0-9'-]{2,}")


def load_stopwords(path) -> set[str]:
    try:
        return {w.strip().lower() for w in open(path, encoding="utf-8") if w.strip()}
    except OSError:
        return set()


def tokenize(text: str, stopwords: set[str]) -> list[str]:
    folded = util.normalize_for_match(text or "")
    return [t for t in TOKEN.findall(folded) if t not in stopwords]


def tf_idf(documents: dict[str, str], stopwords: set[str],
           top_n: int = 12) -> dict[str, list[tuple[str, float]]]:
    """Small standard-library TF-IDF for discriminating terms."""
    tokenized = {k: tokenize(v, stopwords) for k, v in documents.items()}
    total = len(tokenized) or 1
    document_frequency: dict[str, int] = defaultdict(int)
    for tokens in tokenized.values():
        for term in set(tokens):
            document_frequency[term] += 1

    out: dict[str, list[tuple[str, float]]] = {}
    for key, tokens in tokenized.items():
        if not tokens:
            out[key] = []
            continue
        counts: dict[str, int] = defaultdict(int)
        for term in tokens:
            counts[term] += 1
        longest = max(counts.values())
        scores = {
            term: (0.5 + 0.5 * count / longest)
                  * math.log((1 + total) / (1 + document_frequency[term])) + 1e-9
            for term, count in counts.items()}
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
        out[key] = [(t, round(s, 6)) for t, s in ranked]
    return out


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

DIMENSIONS = ("citation_indegree", "coupling_centrality", "pagerank",
              "independent_seed_groups")


DEFAULT_SEED_GROUP_PATTERN = r"^([A-Za-z]+)"


def seed_group(alias: str | None,
               pattern: str = DEFAULT_SEED_GROUP_PATTERN) -> str | None:
    """The catalogue's own grouping, read off the alias.

    "How many independent groups cite this work" only means something relative
    to how the seed bibliography was organised, so the pattern is declared in
    config/ranking.json rather than hardcoded. The default takes the leading
    letters, which groups R0, A1-A7, B1-B6, C1-C5 and D1 as R, A, B, C and D,
    and keeps A5.1 with A5.
    """
    if not alias:
        return None
    try:
        match = re.match(pattern, alias)
    except re.error:
        match = re.match(DEFAULT_SEED_GROUP_PATTERN, alias)
    if not match:
        return None
    return (match.group(1) if match.groups() else match.group(0)).upper()


def coupling_centrality(coupling: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for edge in coupling:
        totals[edge["a"]] += edge["cosine"]
        totals[edge["b"]] += edge["cosine"]
    return dict(totals)


def normalize(values: dict[str, float]) -> dict[str, float]:
    """Min-max to [0, 1]. A flat dimension contributes nothing, not everything."""
    if not values:
        return {}
    low, high = min(values.values()), max(values.values())
    if high == low:
        return {k: 0.0 for k in values}
    return {k: (v - low) / (high - low) for k, v in values.items()}


@dataclasses.dataclass
class WorkRanking:
    work_id: str
    alias: str | None
    title: str | None
    origin: str
    citation_indegree: int
    coupling_centrality: float
    pagerank: float
    independent_seed_groups: int
    citing_aliases: list[str]
    external_cited_by: dict | None
    reading_stage: str
    score: float | None

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def rank_works(corpus, analysis: dict, reviews: dict[str, dict],
               ranking_config: dict,
               exclude: set[str] | None = None) -> list[WorkRanking]:
    exclude = exclude or set()
    group_pattern = ranking_config.get("seed_group_pattern") or DEFAULT_SEED_GROUP_PATTERN
    edges = analysis["citation_edges"]
    indegree = analysis["indegree"]
    ranks = analysis["pagerank"]
    centrality = coupling_centrality(analysis["coupling"])

    alias_of = {w.id: w.primary_alias for w in corpus.works}
    title_of = {w.id: w.title for w in corpus.works}
    for record in analysis["discovered"].values():
        title_of[record["id"]] = record.get("title")

    citers: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        if edge["type"] == "citation":
            citers[edge["target"]].append(edge["source"])

    identifiers = sorted((set(indegree) | set(ranks) | set(title_of)) - exclude)
    rows = []
    for work_id in identifiers:
        citing = sorted({alias_of.get(c, c) for c in citers.get(work_id, [])})
        groups = {seed_group(alias_of.get(c), group_pattern)
                  for c in citers.get(work_id, [])}
        groups.discard(None)
        rows.append(WorkRanking(
            work_id=work_id,
            alias=alias_of.get(work_id),
            title=title_of.get(work_id),
            origin="seed" if work_id in alias_of else "discovered",
            citation_indegree=indegree.get(work_id, 0),
            coupling_centrality=round(centrality.get(work_id, 0.0), 6),
            pagerank=round(ranks.get(work_id, 0.0), 8),
            independent_seed_groups=len(groups),
            citing_aliases=citing,
            external_cited_by=None,
            reading_stage=reviews.get(work_id, {}).get("pass_status", "unread"),
            score=None,
        ))

    weights = ranking_config.get("reading_priority_weights") or {}
    if weights:
        apply_score(rows, weights)
    rows.sort(key=lambda r: (-(r.score if r.score is not None else 0),
                             -r.citation_indegree, r.work_id))
    return rows


def apply_score(rows: list[WorkRanking], weights: dict[str, float]) -> None:
    """Weighted sum of min-max-normalised dimensions. Formula is published."""
    normalized = {
        dimension: normalize({r.work_id: float(getattr(r, dimension)) for r in rows})
        for dimension in DIMENSIONS}
    for row in rows:
        row.score = round(sum(
            float(weights.get(dimension, 0.0)) * normalized[dimension].get(row.work_id, 0.0)
            for dimension in DIMENSIONS), 6)


def sensitivity(rows: list[WorkRanking], weights: dict[str, float],
                deltas: list[float], top_n: int) -> list[dict]:
    """How the shortlist moves under reasonable weight variation.

    A ranking that only survives one exact weighting is not a finding.
    """
    baseline_rows = [dataclasses.replace(r) for r in rows]
    apply_score(baseline_rows, weights)
    baseline_rows.sort(key=lambda r: (-(r.score or 0), r.work_id))
    baseline = [r.work_id for r in baseline_rows[:top_n]]

    out = []
    for dimension in DIMENSIONS:
        for delta in deltas:
            variant = dict(weights)
            variant[dimension] = max(0.0, float(variant.get(dimension, 0.0)) + delta)
            trial = [dataclasses.replace(r) for r in rows]
            apply_score(trial, variant)
            trial.sort(key=lambda r: (-(r.score or 0), r.work_id))
            top = [r.work_id for r in trial[:top_n]]
            out.append({
                "dimension": dimension,
                "delta": delta,
                "weights": {k: round(v, 4) for k, v in sorted(variant.items())},
                "entered": sorted(set(top) - set(baseline)),
                "left": sorted(set(baseline) - set(top)),
                "order_changed": top != baseline,
            })
    return out


def leave_one_out(corpus, analysis: dict, reviews: dict, ranking_config: dict,
                  removed_work_id: str) -> dict:
    """Rebuild the ranking without one work and report what moved."""
    from . import graph as graph_mod

    edges = [e for e in analysis["citation_edges"]
             if e["source"] != removed_work_id and e["target"] != removed_work_id]
    coupling_config = ranking_config.get("coupling", {})
    reduced = {
        **analysis,
        "citation_edges": edges,
        "indegree": graph_mod.citation_indegree(edges),
        "pagerank": graph_mod.pagerank(edges),
        "coupling": graph_mod.bibliographic_coupling(
            edges, min_shared=int(coupling_config.get("min_shared_references", 1))),
    }
    before = [r.work_id for r in rank_works(corpus, analysis, reviews, ranking_config)][:10]
    # The work itself leaves the ranking, not only its edges: otherwise it
    # reappears at the bottom with every dimension zeroed, which reads as a
    # result rather than as the hole it is.
    after = [r.work_id for r in rank_works(corpus, reduced, reviews, ranking_config,
                                           exclude={removed_work_id})][:10]
    return {
        "removed": removed_work_id,
        "top_before": before,
        "top_after": after,
        "entered": sorted(set(after) - set(before)),
        "left": sorted(set(before) - set(after) - {removed_work_id}),
        "order_changed": after != [w for w in before if w != removed_work_id][:len(after)],
    }


# ---------------------------------------------------------------------------
# Researchers
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class AuthorRanking:
    author_id: str
    display_names: list[str]
    works: list[str]
    distinct_works: int
    fractional_credit: float
    seed_groups: int
    top_work_contribution: float
    coauthor_degree: int
    identity_confidence: float
    identity_basis: str
    orcid: str | None
    name_collisions: list[str]

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)


def rank_authors(corpus, analysis: dict, work_rankings: list[WorkRanking],
                 top_n: int = 10,
                 group_pattern: str = DEFAULT_SEED_GROUP_PATTERN) -> list[AuthorRanking]:
    """Credit is fractional and identity confidence is always stated.

    Raw author citation totals are not used as a criterion: they track career
    length, field size, team size, database coverage and name disambiguation at
    least as strongly as they track contribution.
    """
    by_work = {r.work_id: r for r in work_rankings}
    alias_of = {w.id: w.primary_alias for w in corpus.works}
    authors_of: dict[str, list[str]] = defaultdict(list)
    for edge in analysis["authorship_edges"]:
        authors_of[edge["target"]].append(edge["source"])

    top_works = {r.work_id for r in work_rankings[:top_n]}
    records: dict[str, dict] = {}
    for edge in analysis["authorship_edges"]:
        record = records.setdefault(edge["source"], {
            "display_names": set(), "works": set(), "credit": 0.0,
            "groups": set(), "top_contribution": 0.0, "coauthors": set(),
            "confidence": edge["identity_confidence"], "basis": edge["identity_basis"],
        })
        record["display_names"].add(edge["author_display"])
        record["works"].add(edge["target"])
        team = max(1, len(authors_of.get(edge["target"], [])))
        indegree = by_work[edge["target"]].citation_indegree if edge["target"] in by_work else 0
        record["credit"] += indegree / team
        group = seed_group(alias_of.get(edge["target"]), group_pattern)
        if group:
            record["groups"].add(group)
        if edge["target"] in top_works:
            record["top_contribution"] += 1.0 / team
        record["coauthors"] |= {a for a in authors_of.get(edge["target"], [])
                                if a != edge["source"]}
        record["confidence"] = min(record["confidence"], edge["identity_confidence"])

    def surname_key(author_id: str) -> str:
        """Surname portion of an author id, with or without the author: prefix."""
        bare = author_id.split(":", 1)[1] if author_id.startswith("author:") else author_id
        return bare.split(" ", 1)[0]

    surname_index: dict[str, set[str]] = defaultdict(set)
    for author_id in records:
        surname_index[surname_key(author_id)].add(author_id)

    out = []
    for author_id, record in sorted(records.items()):
        collisions = sorted(surname_index[surname_key(author_id)] - {author_id})
        out.append(AuthorRanking(
            author_id=author_id,
            display_names=sorted(record["display_names"]),
            works=sorted(record["works"]),
            distinct_works=len(record["works"]),
            fractional_credit=round(record["credit"], 4),
            seed_groups=len(record["groups"]),
            top_work_contribution=round(record["top_contribution"], 4),
            coauthor_degree=len(record["coauthors"]),
            identity_confidence=record["confidence"],
            identity_basis=record["basis"],
            orcid=None,
            name_collisions=collisions,
        ))
    out.sort(key=lambda a: (-a.fractional_credit, -a.distinct_works, a.author_id))
    return out


def build_clusters(corpus, analysis: dict, stopwords: set[str]) -> list[dict]:
    """One record per connected component, with its own discriminating terms."""
    title_of = {w.id: w.title for w in corpus.works}
    alias_of = {w.id: w.primary_alias for w in corpus.works}
    for record in analysis["discovered"].values():
        title_of[record["id"]] = record.get("title")

    corpus_documents = {}
    for index, members in enumerate(analysis["clusters"], start=1):
        corpus_documents[str(index)] = " ".join(
            (title_of.get(m) or "") for m in members)
    terms = tf_idf(corpus_documents, stopwords) if corpus_documents else {}

    clusters = []
    for index, members in enumerate(analysis["clusters"], start=1):
        member_set = set(members)
        internal = [e for e in analysis["coupling"]
                    if e["a"] in member_set and e["b"] in member_set]
        internal.sort(key=lambda e: (-e["cosine"], e["a"], e["b"]))
        years = [w.year for w in corpus.works
                 if w.id in member_set and w.year] + \
                [r.get("year") for r in analysis["discovered"].values()
                 if r["id"] in member_set and r.get("year")]
        clusters.append({
            "index": index,
            # Neutral by default, and editable by a human.
            "name": f"Cluster {index}",
            "members": members,
            "member_aliases": [alias_of.get(m) for m in members],
            "size": len(members),
            "strongest_pairs": internal[:10],
            "terms": terms.get(str(index), []),
            "earliest_year": min(years) if years else None,
            "latest_year": max(years) if years else None,
        })
    return clusters


def build_survey(corpus, analysis: dict, reviews: dict, ranking_config: dict,
                 stopwords: set[str]) -> dict:
    work_rankings = rank_works(corpus, analysis, reviews, ranking_config)
    author_rankings = rank_authors(
        corpus, analysis, work_rankings,
        group_pattern=ranking_config.get("seed_group_pattern")
        or DEFAULT_SEED_GROUP_PATTERN)
    clusters = build_clusters(corpus, analysis, stopwords)

    weights = ranking_config.get("reading_priority_weights") or {}
    sensitivity_config = ranking_config.get("sensitivity") or {}
    sensitivity_rows = sensitivity(
        work_rankings, weights,
        [float(d) for d in sensitivity_config.get("weight_deltas", [])],
        int(sensitivity_config.get("top_n", 10))) if weights else []

    highest = work_rankings[0].work_id if work_rankings else None
    holdout = leave_one_out(corpus, analysis, reviews, ranking_config, highest) \
        if highest else None

    repeated_authors = [a for a in author_rankings if a.distinct_works > 1]
    unresolved = [e for e in analysis.get("unresolved") or []]
    years = [w.year for w in corpus.works if w.year]

    return {
        **util.derived_header({}, "survey"),
        "weights": weights,
        "formula": ("score = " + " + ".join(
            f"{weights.get(d, 0)}*normalized({d})" for d in DIMENSIONS)) if weights else None,
        "work_rankings": [r.as_dict() for r in work_rankings],
        "author_rankings": [a.as_dict() for a in author_rankings],
        "clusters": clusters,
        "sensitivity": sensitivity_rows,
        "holdout": holdout,
        "repeated_authors": [a.as_dict() for a in repeated_authors],
        "coverage": {
            "earliest_year": min(years) if years else None,
            "latest_year": max(years) if years else None,
            "works_without_year": sorted(
                w.primary_alias for w in corpus.works if not w.year),
            "works_without_extraction": [],
        },
        "unresolved_references": unresolved,
        "strongest_coupling": analysis["coupling"][:15],
    }


# ---------------------------------------------------------------------------
# Pages
#
# Imported lazily by site.py so the two modules do not import each other at
# module load time.
# ---------------------------------------------------------------------------


def _site():
    from . import site

    return site


def _work_link(data, work_id: str, depth: int) -> str:
    site = _site()
    alias = next((w.primary_alias for w in data.corpus.works if w.id == work_id), None)
    if alias:
        return (f'<a href="{site.esc(site.work_href(depth, alias))}">'
                f'{site.esc(alias)}</a>')
    label = work_id if len(work_id) <= 40 else work_id[:39] + "…"
    return f'<code title="{site.esc(work_id)}">{site.esc(label)}</code>'


def build_graph_page(data) -> str:
    site = _site()
    analysis = data.analysis or {}
    edges = [e for e in data.edges if e["type"] == "citation"]
    coupling = [e for e in data.edges if e["type"] == "coupling"]

    citation_rows = [[
        _work_link(data, e["source"], 1), _work_link(data, e["target"], 1),
        str(e["weight"]), site.badge(e.get("method") or "unknown"),
        f'{e.get("confidence", 0):.2f}',
        f'<details><summary>{len(e["raw_references"])} raw</summary><pre>'
        f'{site.esc(chr(10).join(e["raw_references"]))}</pre></details>',
    ] for e in edges[:200]]

    coupling_rows = [[
        _work_link(data, e["a"], 1), _work_link(data, e["b"], 1),
        str(e["shared"]), f'{e["cosine"]:.4f}',
        f'<details><summary>shared</summary><ul class="plain">' + "".join(
            f"<li>{_work_link(data, s, 1)}</li>" for s in e["shared_references"])
        + "</ul></details>",
    ] for e in coupling[:100]]

    body = f"""
<div class="notice"><strong>These are computed observations.</strong> Shared
references indicate probable intellectual proximity. They do not indicate
agreement, influence direction, or correctness. A paper may not be described as
supporting or contradicting a claim on this evidence alone; that needs a human
second pass.</div>
<h2>Summary</h2>
{site.definition_list([
    ("Citation edges", str(len(edges))),
    ("Coupling edges", str(len(coupling))),
    ("Clusters", str(len(analysis.get("clusters") or []))),
    ("Cluster threshold", str(analysis.get("cluster_threshold"))),
])}
<h2>Citation edges</h2>
<p class="muted">citing &rarr; cited. Every edge keeps the raw reference string
and the evidence used to resolve it.</p>
{site.table(["Citing", "Cited", "Weight", "Method", "Confidence", "Raw references"],
            citation_rows, empty="No citation edge has been resolved.")}
<h2>Bibliographic coupling</h2>
<p class="muted">Cosine is
|R(A) &cap; R(B)| / &radic;(|R(A)|&middot;|R(B)|), so a work with a very long
bibliography does not appear closest to everything.</p>
{site.table(["A", "B", "Shared", "Cosine", "Shared references"], coupling_rows,
            empty="No coupling edge above the minimum shared-reference threshold.")}
"""
    return site.page("Citation graph", body, 1, public=data.public)


def build_survey_page(data) -> str:
    site = _site()
    survey = data.survey or {}
    if not survey:
        return site.build_empty_state(
            "Survey", "No survey has been generated yet.", 1, data.public)

    ranking_rows = [[
        _work_link(data, r["work_id"], 1),
        site.esc((r["title"] or "—")[:70]),
        site.badge(r["origin"]),
        str(r["citation_indegree"]),
        f'{r["coupling_centrality"]:.4f}',
        f'{r["pagerank"]:.6f}',
        str(r["independent_seed_groups"]),
        site.badge(r["reading_stage"]),
        f'{r["score"]:.4f}' if r["score"] is not None else "—",
        ", ".join(site.esc(a) for a in r["citing_aliases"]) or "—",
    ] for r in survey["work_rankings"][:40]]

    author_rows = [[
        site.esc(a["display_names"][0] if a["display_names"] else a["author_id"]),
        str(a["distinct_works"]),
        f'{a["fractional_credit"]:.3f}',
        str(a["seed_groups"]),
        f'{a["top_work_contribution"]:.3f}',
        str(a["coauthor_degree"]),
        site.badge(a["identity_basis"]) + f' {a["identity_confidence"]:.2f}',
        ", ".join(site.esc(c) for c in a["name_collisions"]) or "none",
    ] for a in survey["author_rankings"][:30]]

    cluster_sections = []
    for cluster in survey["clusters"]:
        members = "".join(f"<li>{_work_link(data, m, 1)} "
                          f'<span class="muted">{site.esc(cluster["member_aliases"][i] or "")}</span></li>'
                          for i, m in enumerate(cluster["members"]))
        pairs = site.table(
            ["A", "B", "Shared", "Cosine", "Shared references"],
            [[_work_link(data, p["a"], 1), _work_link(data, p["b"], 1),
              str(p["shared"]), f'{p["cosine"]:.4f}',
              ", ".join(_work_link(data, s, 1) for s in p["shared_references"])]
             for p in cluster["strongest_pairs"]],
            empty="No internal coupling pair.")
        terms = ", ".join(f'{site.esc(t)} <span class="muted">({s:.2f})</span>'
                          for t, s in cluster["terms"]) or "—"
        cluster_sections.append(f"""
<section id="cluster-{cluster['index']}">
<h3>{site.esc(cluster['name'])} <span class="muted">({cluster['size']} works,
{site.esc(cluster['earliest_year'] or '?')}&ndash;{site.esc(cluster['latest_year'] or '?')})</span></h3>
<p class="muted">The name is neutral by default and is meant to be edited by a human.</p>
<h4>Members</h4><ul class="plain">{members}</ul>
<h4>Strongest coupling pairs, with the exact shared references</h4>{pairs}
<h4>Top discriminating terms (TF&ndash;IDF)</h4><p>{terms}</p>
</section>""")

    sensitivity_rows = [[
        site.badge(row["dimension"]), f'{row["delta"]:+.2f}',
        "yes" if row["order_changed"] else "no",
        ", ".join(_work_link(data, w, 1) for w in row["entered"]) or "—",
        ", ".join(_work_link(data, w, 1) for w in row["left"]) or "—",
    ] for row in survey["sensitivity"]]

    holdout = survey.get("holdout")
    holdout_html = '<p class="muted">No ranking to perturb.</p>'
    if holdout:
        holdout_html = site.definition_list([
            ("Removed", _work_link(data, holdout["removed"], 1)),
            ("Order changed", "yes" if holdout["order_changed"] else "no"),
            ("Entered the top 10",
             ", ".join(_work_link(data, w, 1) for w in holdout["entered"]) or "none"),
            ("Left the top 10",
             ", ".join(_work_link(data, w, 1) for w in holdout["left"]) or "none"),
        ])

    coverage = survey["coverage"]
    body = f"""
<div class="notice"><strong>Computed observations, not conclusions.</strong>
Everything on this page is derived mechanically from resolved references. It
ranks candidates for human reading; it does not assess proof validity,
contribution, or correctness. Human interpretation lives in the pass-two and
pass-three notes linked from each work page.</div>

<h2>Reading-priority ranking</h2>
<p class="muted">Dimensions are shown separately. {site.esc(survey["formula"] or
"No combined score is defined; only the separate dimensions are shown.")}
Each component is min-max normalised across the corpus before weighting.</p>
{site.table(["Work", "Title", "Origin", "Indegree", "Coupling centrality",
             "PageRank", "Seed groups", "Stage", "Score", "Cited by"],
            ranking_rows, empty="Nothing to rank yet.")}
<p class="muted">External citation counts are not shown because none has been
recorded. When they are, they carry a provider and a snapshot date, and they
are never compared as if they were timeless or field-neutral.</p>

<h2>Sensitivity of the shortlist to the weights</h2>
<p class="muted">A ranking that survives only one exact weighting is not a
finding.</p>
{site.table(["Dimension", "Weight change", "Order changed", "Entered", "Left"],
            sensitivity_rows, empty="No weights are configured.")}

<h2>Leaving out the highest-ranked work</h2>
{holdout_html}

<h2>Researchers</h2>
<p class="muted">Credit is fractional: a work's credit is divided by its number
of authors. A normalised name is a candidate identity, never a confirmed
person, and raw author citation totals are deliberately not used as a
criterion.</p>
{site.table(["Name", "Works", "Fractional credit", "Seed groups",
             "Top-work contribution", "Coauthors", "Identity", "Name collisions"],
            author_rows, empty="No author identity resolved.")}

<h2>Clusters</h2>
{"".join(cluster_sections) or '<p class="muted">No cluster was formed.</p>'}

<h2>Coverage and gaps</h2>
{site.definition_list([
    ("Earliest year", site.esc(coverage["earliest_year"] or "unknown")),
    ("Latest year", site.esc(coverage["latest_year"] or "unknown")),
    ("Works with no recorded year",
     ", ".join(site.esc(a) for a in coverage["works_without_year"]) or "none"),
])}
<p class="muted">The seed bibliography encodes the choices and access of whoever
assembled it. Missing schools, languages, negative results and newer work are
expected and are not evidence of absence.</p>
"""
    return site.page("Survey", body, 1, public=data.public)
