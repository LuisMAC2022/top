"""Assemble resolution output into versioned graph exports.

data/*.jsonl are the reproducible, diffable source of truth for everything the
site and the survey display. Each carries a provenance header recording the
generator, the command and the hashes of its inputs.
"""

from __future__ import annotations

from pathlib import Path

from . import graph, references, resolve, util
from .model import Corpus
from .util import Workspace


def discovered_works(resolutions: list[resolve.Resolution]) -> dict[str, dict]:
    """Metadata-only candidate nodes. Discovery never queues a download."""
    out: dict[str, dict] = {}
    for resolution in resolutions:
        if resolution.status != resolve.STATUS_DISCOVERED or not resolution.target_id:
            continue
        parsed = resolution.parsed
        record = out.setdefault(resolution.target_id, {
            "id": resolution.target_id,
            "origin": "discovered",
            "title": parsed.get("title"),
            "authors": list(parsed.get("authors") or []),
            "year": parsed.get("year"),
            "doi": parsed.get("doi"),
            "isbn": parsed.get("isbn"),
            "acquisition": "not_requested",
            "cited_by": [],
            "raw_references": [],
        })
        if resolution.citing_work_id not in record["cited_by"]:
            record["cited_by"].append(resolution.citing_work_id)
            record["cited_by"].sort()
        if resolution.raw not in record["raw_references"]:
            record["raw_references"].append(resolution.raw)
            record["raw_references"].sort()
    return out


def merge_discovered(records: dict[str, dict]) -> tuple[dict[str, dict], dict[str, str]]:
    """Collapse discovered records that are the same work under different evidence.

    The same paper cited twice may carry a DOI in one bibliography and not in
    the other, which otherwise yields two nodes for one work and inflates every
    count derived from them. Merging requires an exact match on all three of
    normalised title, year and first-author surname — the same strength as the
    local title+year+author rule — so this stays a precision-first rule rather
    than a title-similarity guess.

    Returns the merged records and a map from every old id to its canonical id.
    """
    groups: dict[tuple[str, int, str], list[dict]] = {}
    alias: dict[str, str] = {}
    unmergeable: dict[str, dict] = {}

    for record in sorted(records.values(), key=lambda r: r["id"]):
        title = util.normalize_for_match(record.get("title") or "")
        year = record.get("year")
        authors = record.get("authors") or []
        first = util.normalize_for_match(
            references.surname(authors[0])) if authors else ""
        if not title or year is None or not first:
            unmergeable[record["id"]] = record
            alias[record["id"]] = record["id"]
            continue
        groups.setdefault((title, year, first), []).append(record)

    merged: dict[str, dict] = dict(unmergeable)
    for _key, members in sorted(groups.items()):
        # An identifier-bearing id is the more stable canonical choice.
        members.sort(key=lambda r: (0 if r.get("doi") else 1 if r.get("isbn") else 2,
                                    r["id"]))
        canonical = members[0]
        winner = dict(canonical)
        winner["merged_from"] = []
        for other in members[1:]:
            winner["cited_by"] = sorted(set(winner["cited_by"]) | set(other["cited_by"]))
            winner["raw_references"] = sorted(
                set(winner["raw_references"]) | set(other["raw_references"]))
            winner["doi"] = winner.get("doi") or other.get("doi")
            winner["isbn"] = winner.get("isbn") or other.get("isbn")
            winner["merged_from"].append({
                "id": other["id"],
                "evidence": "exact title, year and first-author surname",
            })
        for member in members:
            alias[member["id"]] = canonical["id"]
        merged[canonical["id"]] = winner
    return merged, alias


def citation_edges_including_discovered(resolutions: list[resolve.Resolution],
                                        alias: dict[str, str] | None = None) -> list[dict]:
    """Discovered targets become real citation edges; only download is withheld."""
    alias = alias or {}
    promoted = []
    for resolution in resolutions:
        if resolution.status == resolve.STATUS_DISCOVERED and resolution.target_id:
            clone = resolve.Resolution(**{
                **{k: getattr(resolution, k) for k in (
                    "citing_work_id", "citing_alias", "reference_index", "raw",
                    "parsed", "target_id", "candidates")},
                "status": "resolved",
                "method": "discovery",
                "confidence": 0.0,
                "reason": resolution.reason,
            })
            clone.target_id = alias.get(resolution.target_id, resolution.target_id)
            promoted.append(clone)
        else:
            promoted.append(resolution)
    return graph.citation_edges(promoted)


# Untrusted input reaches these structures through parsed bibliographies, so
# the derived graph is bounded. Exceeding a bound is a visible error, not a
# silently truncated graph.
MAX_NODES = 50_000
MAX_EDGES = 500_000


class GraphTooLarge(Exception):
    pass


def analyze(ws: Workspace, corpus: Corpus, resolutions: list[resolve.Resolution],
            ranking: dict) -> dict:
    discovered, alias = merge_discovered(discovered_works(resolutions))
    edges = citation_edges_including_discovered(resolutions, alias)
    authorship = graph.authorship_edges(corpus, discovered)

    coupling_config = ranking.get("coupling", {})
    min_shared = int(coupling_config.get("min_shared_references", 1))
    threshold = float(coupling_config.get("cluster_threshold", 0.2))
    coupling = graph.bibliographic_coupling(edges, min_shared=min_shared)
    cocitation = graph.co_citation(edges, min_shared=2)

    nodes = ({e["source"] for e in edges} | {e["target"] for e in edges}
             | {w.id for w in corpus.works})
    if len(nodes) > MAX_NODES:
        raise GraphTooLarge(
            f"{len(nodes)} nodes exceeds the {MAX_NODES} bound; narrow the corpus "
            "or raise MAX_NODES deliberately")
    total_edges = len(edges) + len(authorship) + len(coupling) + len(cocitation)
    if total_edges > MAX_EDGES:
        raise GraphTooLarge(
            f"{total_edges} edges exceeds the {MAX_EDGES} bound")

    pagerank_config = ranking.get("pagerank", {})
    ranks = graph.pagerank(
        edges,
        damping=float(pagerank_config.get("damping", 0.85)),
        iterations=int(pagerank_config.get("iterations", 100)),
        tolerance=float(pagerank_config.get("tolerance", 1e-10)))
    indegree = graph.citation_indegree(edges)
    clusters = graph.connected_components(coupling, threshold)

    return {
        "discovered": discovered,
        "citation_edges": edges,
        "authorship_edges": authorship,
        "coupling": coupling,
        "co_citation": cocitation,
        "pagerank": ranks,
        "indegree": indegree,
        "clusters": clusters,
        "cluster_threshold": threshold,
        "discovered_alias": alias,
    }


def export(ws: Workspace, corpus: Corpus, resolutions: list[resolve.Resolution],
           analysis: dict, input_hashes: dict[str, str]) -> list[Path]:
    """Write the versioned JSONL exports plus a single analysis summary."""
    ws.data.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    header = util.derived_header(input_hashes, "resolve+analyze")

    def emit(name: str, rows: list) -> None:
        path = ws.data / name
        util.write_jsonl_atomic(path, [{"_meta": header}] + rows)
        written.append(path)

    works = []
    for work in corpus.works:
        works.append({
            "id": work.id, "alias": work.primary_alias, "origin": "seed",
            "title": work.title, "authors": work.authors, "year": work.year,
            "work_type": work.work_type, "access": work.rights.access,
            "identifiers": work.identifiers,
            "canonical_id_kind": work.canonical_id_kind,
        })
    works += [
        {"id": r["id"], "alias": None, "origin": "discovered", "title": r["title"],
         "authors": r["authors"], "year": r["year"], "work_type": "unknown",
         "access": "unknown",
         "identifiers": {k: v for k, v in (("doi", r["doi"]), ("isbn", r["isbn"])) if v},
         "canonical_id_kind": "doi" if r["doi"] else "isbn" if r["isbn"] else "local"}
        for r in sorted(analysis["discovered"].values(), key=lambda x: x["id"])]
    emit("works.jsonl", works)

    emit("references.jsonl", [r.as_dict() for r in resolutions])

    authors: dict[str, dict] = {}
    for edge in analysis["authorship_edges"]:
        record = authors.setdefault(edge["source"], {
            "id": edge["source"], "display_names": [], "works": [],
            "identity_confidence": edge["identity_confidence"],
            "identity_basis": edge["identity_basis"],
            "orcid": None,
        })
        if edge["author_display"] not in record["display_names"]:
            record["display_names"].append(edge["author_display"])
            record["display_names"].sort()
        if edge["target"] not in record["works"]:
            record["works"].append(edge["target"])
            record["works"].sort()
    emit("authors.jsonl", [authors[k] for k in sorted(authors)])

    emit("edges.jsonl",
         analysis["citation_edges"] + analysis["authorship_edges"]
         + analysis["coupling"] + analysis["co_citation"])

    summary = {
        **header,
        "counts": {
            "works": len(works),
            "seed_works": len(corpus.works),
            "discovered_works": len(analysis["discovered"]),
            "citation_edges": len(analysis["citation_edges"]),
            "authorship_edges": len(analysis["authorship_edges"]),
            "coupling_edges": len(analysis["coupling"]),
            "co_citation_edges": len(analysis["co_citation"]),
            "clusters": len(analysis["clusters"]),
            "authors": len(authors),
        },
        "cluster_threshold": analysis["cluster_threshold"],
        "clusters": analysis["clusters"],
        "pagerank": analysis["pagerank"],
        "indegree": analysis["indegree"],
    }
    util.write_json_atomic(ws.data / "analysis.json", summary)
    written.append(ws.data / "analysis.json")
    return written


def promotion_candidates(analysis: dict, max_new: int, min_citations: int,
                         year_from: int | None = None,
                         year_to: int | None = None) -> list[dict]:
    """A reviewed queue, bounded on every axis. Nothing is downloaded here.

    Reference discovery does not recurse: a candidate is only ever proposed for
    a human to move into the manifest, which is what keeps a bibliography of a
    few hundred entries from becoming an uncontrolled crawl.
    """
    rows = []
    for record in analysis["discovered"].values():
        citations = len(record["cited_by"])
        if citations < min_citations:
            continue
        year = record.get("year")
        if year_from and (year is None or year < year_from):
            continue
        if year_to and (year is None or year > year_to):
            continue
        rows.append({**record, "citing_count": citations})
    rows.sort(key=lambda r: (-r["citing_count"], r["id"]))
    return rows[:max_new]
