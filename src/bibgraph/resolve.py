"""Reference resolution: conservative identity matching with kept evidence.

Optimised for precision, not recall. A missing edge is visible on the work
page; a false merge silently distorts every downstream number, so anything
short of a unique high-confidence match goes to the manual queue with its
candidate scores recorded.
"""

from __future__ import annotations

import dataclasses
import json
import os
import urllib.parse
from pathlib import Path

from . import references, util
from .model import Corpus, Work
from .util import Workspace

# A match is accepted automatically only when it is both strong and unique.
AUTO_ACCEPT = 0.95
AMBIGUITY_MARGIN = 0.05

SOURCE_SCORES = {
    "local-doi": 1.0,
    "local-isbn": 1.0,
    "local-title-year-author": 0.96,
    "local-title-year": 0.90,
    "local-title": 0.72,
    "crossref-doi": 0.97,
    "crossref-query": 0.0,       # scored from the response, never assumed
    "openalex": 0.0,
}

STATUS_RESOLVED = "resolved"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_UNRESOLVED = "unresolved"
STATUS_DISCOVERED = "discovered"


@dataclasses.dataclass
class Candidate:
    target_id: str
    source: str
    score: float
    evidence: dict

    def as_dict(self) -> dict:
        return {"target_id": self.target_id, "source": self.source,
                "score": round(self.score, 4), "evidence": self.evidence}


@dataclasses.dataclass
class Resolution:
    citing_work_id: str
    citing_alias: str
    reference_index: int
    raw: str
    parsed: dict
    status: str
    target_id: str | None
    method: str | None
    confidence: float
    candidates: list[Candidate]
    reason: str | None = None

    def as_dict(self) -> dict:
        return {
            "citing_work_id": self.citing_work_id,
            "citing_alias": self.citing_alias,
            "reference_index": self.reference_index,
            "raw": self.raw,
            "parsed": self.parsed,
            "status": self.status,
            "target_id": self.target_id,
            "method": self.method,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "candidates": [c.as_dict() for c in self.candidates],
        }


# ---------------------------------------------------------------------------
# Local index
# ---------------------------------------------------------------------------


class LocalIndex:
    """Corpus works indexed by every identity the manifest records."""

    def __init__(self, corpus: Corpus, documents: dict[str, dict] | None = None):
        self.by_doi: dict[str, Work] = {}
        self.by_isbn: dict[str, Work] = {}
        self.by_title: dict[str, list[Work]] = {}
        documents = documents or {}
        for work in corpus.works:
            doi = references.normalize_doi(work.identifiers.get("doi"))
            if doi:
                self.by_doi[doi] = work
            isbn = references.normalize_isbn(work.identifiers.get("isbn"))
            if isbn:
                self.by_isbn[isbn] = work
            titles = {work.title}
            extracted = documents.get(work.id, {}).get("fields", {}).get("title") or {}
            if extracted.get("status") == "present" and extracted.get("text"):
                titles.add(extracted["text"])
            for title in titles:
                key = util.normalize_for_match(title)
                if key:
                    self.by_title.setdefault(key, []).append(work)

    def lookup(self, parsed: references.ParsedReference) -> list[Candidate]:
        candidates: list[Candidate] = []
        if parsed.doi and parsed.doi in self.by_doi:
            work = self.by_doi[parsed.doi]
            candidates.append(Candidate(work.id, "local-doi", SOURCE_SCORES["local-doi"],
                                        {"doi": parsed.doi, "alias": work.primary_alias}))
        if parsed.isbn and parsed.isbn in self.by_isbn:
            work = self.by_isbn[parsed.isbn]
            candidates.append(Candidate(work.id, "local-isbn", SOURCE_SCORES["local-isbn"],
                                        {"isbn": parsed.isbn, "alias": work.primary_alias}))

        key = parsed.normalized_title
        for work in self.by_title.get(key, []):
            year_ok = parsed.year is not None and work.year == parsed.year
            author_ok = bool(parsed.first_author_key) and any(
                util.normalize_for_match(references.surname(a)) == parsed.first_author_key
                for a in work.authors)
            if year_ok and author_ok:
                source = "local-title-year-author"
            elif year_ok:
                source = "local-title-year"
            else:
                source = "local-title"
            candidates.append(Candidate(
                work.id, source, SOURCE_SCORES[source],
                {"title": key, "year_match": year_ok, "first_author_match": author_ok,
                 "alias": work.primary_alias}))
        return candidates


# ---------------------------------------------------------------------------
# Optional external enrichment
# ---------------------------------------------------------------------------


class CrossrefClient:
    """Polite, cached, serial Crossref access. Entirely optional.

    Crossref publishes its limits in response headers, so the client adapts to
    what it is told rather than hardcoding a rate, and sends a mailto so the
    request is identified.
    """

    BASE = "https://api.crossref.org/works"

    def __init__(self, fetcher, cache_dir: Path, mailto: str | None = None):
        self.fetcher = fetcher
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.mailto = mailto or os.environ.get("CROSSREF_MAILTO") \
            or os.environ.get("BIBGRAPH_CONTACT_EMAIL")
        self.last_headers: dict[str, str] = {}

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / f"crossref-{util.sha256_bytes(url.encode())[:32]}.json"

    def _get(self, url: str) -> dict | None:
        cached = self._cache_path(url)
        if cached.exists():
            return util.read_json(cached)
        try:
            response = self.fetcher.fetch(url, expected_media_type="application/json",
                                          min_bytes=2)
        except Exception:  # noqa: BLE001 - any failure means "no enrichment"
            return None
        try:
            payload = json.loads(response.body_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        finally:
            response.body_path.unlink(missing_ok=True)
        self.last_headers = response.headers
        util.write_json_atomic(cached, payload)
        return payload

    def by_doi(self, doi: str) -> dict | None:
        url = f"{self.BASE}/{urllib.parse.quote(doi, safe='')}"
        if self.mailto:
            url += "?" + urllib.parse.urlencode({"mailto": self.mailto})
        payload = self._get(url)
        return (payload or {}).get("message")

    def query(self, parsed: references.ParsedReference, rows: int = 5) -> list[dict]:
        if not parsed.title:
            return []
        params = {"query.bibliographic": parsed.raw[:400], "rows": str(rows)}
        if self.mailto:
            params["mailto"] = self.mailto
        payload = self._get(f"{self.BASE}?{urllib.parse.urlencode(params)}")
        return ((payload or {}).get("message") or {}).get("items") or []


def score_crossref_item(parsed: references.ParsedReference, item: dict) -> tuple[float, dict]:
    """Conservative similarity; a weak match must not creep over the threshold."""
    titles = item.get("title") or []
    item_title = util.normalize_for_match(titles[0] if titles else "")
    evidence = {"crossref_title": titles[0] if titles else None,
                "doi": item.get("DOI")}
    if not item_title or not parsed.normalized_title:
        return 0.0, evidence

    left, right = set(parsed.normalized_title.split()), set(item_title.split())
    jaccard = len(left & right) / len(left | right) if left | right else 0.0
    evidence["title_jaccard"] = round(jaccard, 3)

    score = 0.80 * jaccard
    issued = ((item.get("issued") or {}).get("date-parts") or [[None]])[0][0]
    evidence["crossref_year"] = issued
    if parsed.year and issued == parsed.year:
        score += 0.12
    elif parsed.year and issued and abs(issued - parsed.year) > 1:
        score -= 0.25
    item_authors = {util.normalize_for_match(a.get("family", ""))
                    for a in (item.get("author") or [])}
    if parsed.first_author_key and parsed.first_author_key in item_authors:
        score += 0.10
        evidence["first_author_match"] = True
    return max(0.0, min(score, 0.99)), evidence


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def resolve_reference(citing: Work, parsed: references.ParsedReference,
                      index: LocalIndex, crossref: CrossrefClient | None = None,
                      allow_discovery: bool = True) -> Resolution:
    candidates = index.lookup(parsed)

    if crossref is not None and not _is_decisive(candidates):
        if parsed.doi:
            item = crossref.by_doi(parsed.doi)
            if item:
                candidates.append(Candidate(
                    f"doi:{references.normalize_doi(item.get('DOI')) or parsed.doi}",
                    "crossref-doi", SOURCE_SCORES["crossref-doi"],
                    {"doi": item.get("DOI"), "title": (item.get("title") or [None])[0]}))
        else:
            for item in crossref.query(parsed):
                score, evidence = score_crossref_item(parsed, item)
                doi = references.normalize_doi(item.get("DOI"))
                if doi:
                    candidates.append(Candidate(f"doi:{doi}", "crossref-query",
                                                score, evidence))

    candidates.sort(key=lambda c: (-c.score, c.target_id))
    base = dict(
        citing_work_id=citing.id, citing_alias=citing.primary_alias,
        reference_index=parsed.index, raw=parsed.raw, parsed=parsed.as_dict(),
        candidates=candidates)

    if not candidates:
        if allow_discovery and (parsed.doi or parsed.isbn or parsed.title):
            target = discovered_id(parsed)
            return Resolution(**base, status=STATUS_DISCOVERED, target_id=target,
                              method="discovery", confidence=0.0,
                              reason="no corpus match; recorded as a metadata-only "
                                     "candidate, not queued for download")
        return Resolution(**base, status=STATUS_UNRESOLVED, target_id=None,
                          method=None, confidence=0.0,
                          reason="no identifier or title candidate could be extracted")

    best = candidates[0]
    rival = candidates[1] if len(candidates) > 1 else None
    if rival and rival.target_id != best.target_id and \
            best.score - rival.score < AMBIGUITY_MARGIN:
        return Resolution(**base, status=STATUS_AMBIGUOUS, target_id=None,
                          method=best.source, confidence=best.score,
                          reason=f"top two candidates are within {AMBIGUITY_MARGIN} "
                                 f"({best.target_id} vs {rival.target_id}); "
                                 "left for human review rather than merged")
    if best.score < AUTO_ACCEPT:
        return Resolution(**base, status=STATUS_AMBIGUOUS, target_id=None,
                          method=best.source, confidence=best.score,
                          reason=f"best score {best.score:.2f} is below the "
                                 f"{AUTO_ACCEPT} auto-accept threshold")
    return Resolution(**base, status=STATUS_RESOLVED, target_id=best.target_id,
                      method=best.source, confidence=best.score, reason=None)


def _is_decisive(candidates: list[Candidate]) -> bool:
    return any(c.score >= AUTO_ACCEPT for c in candidates)


def discovered_id(parsed: references.ParsedReference) -> str:
    if parsed.doi:
        return f"doi:{parsed.doi}"
    if parsed.isbn:
        return f"isbn:{parsed.isbn}"
    return util.local_id(f"{parsed.first_author_key}|{parsed.normalized_title}|{parsed.year}")


def resolve_corpus(ws: Workspace, corpus: Corpus, documents: dict[str, dict],
                   crossref: CrossrefClient | None = None,
                   allow_discovery: bool = True) -> list[Resolution]:
    index = LocalIndex(corpus, documents)
    resolutions: list[Resolution] = []
    by_id = corpus.by_id()
    for work_id, document in sorted(documents.items()):
        work = by_id.get(work_id)
        if work is None:
            continue
        parsed_refs = references.parse_all(document.get("raw_references") or [])
        for parsed in parsed_refs:
            resolutions.append(resolve_reference(
                work, parsed, index, crossref=crossref, allow_discovery=allow_discovery))
    return resolutions


def summarize(resolutions: list[Resolution]) -> dict:
    counts: dict[str, int] = {}
    methods: dict[str, int] = {}
    for resolution in resolutions:
        counts[resolution.status] = counts.get(resolution.status, 0) + 1
        if resolution.method:
            methods[resolution.method] = methods.get(resolution.method, 0) + 1
    accepted = [r for r in resolutions if r.status == STATUS_RESOLVED]
    return {
        "references": len(resolutions),
        "counts": dict(sorted(counts.items())),
        "methods": dict(sorted(methods.items())),
        "auto_accepted": len(accepted),
        "manual_queue": sorted({r.raw[:80] for r in resolutions
                                if r.status in (STATUS_AMBIGUOUS, STATUS_UNRESOLVED)}),
    }


def exit_code_for(resolutions: list[Resolution], strict: bool = False) -> int:
    summary = summarize(resolutions)
    if strict and summary["counts"].get(STATUS_UNRESOLVED):
        return util.EXIT_INCOMPLETE
    return util.EXIT_OK
