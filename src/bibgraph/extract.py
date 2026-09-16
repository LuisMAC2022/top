"""First-pass extraction: structure with provenance, never a claim of reading.

This produces the material a human needs for Keshav's first pass — title,
abstract, introduction, section hierarchy, conclusions, bibliography — and
records for every field how it was found, how confident that method is, and
which bytes it came from. An absent value always carries a reason state; it is
never rendered as an empty success.
"""

from __future__ import annotations

import dataclasses
import re
import unicodedata
from pathlib import Path

from . import extract_html, extract_pdf, util
from .model import Corpus, Work
from .store import Store
from .util import Workspace

FIELD_NAMES = ("title", "abstract", "introduction", "conclusion", "references")

# What each kind of document may legitimately lack. Articles, books, lecture
# notes and OEIS-style sequence pages do not share one structure, so a single
# expectation set would manufacture false "missing" fields.
EXPECTATIONS = {
    "article":    {"abstract": "expected", "introduction": "expected",
                   "conclusion": "expected", "references": "expected"},
    "book":       {"abstract": "optional", "introduction": "expected",
                   "conclusion": "not_applicable", "references": "expected"},
    "notes":      {"abstract": "optional", "introduction": "optional",
                   "conclusion": "optional", "references": "optional"},
    "sequence":   {"abstract": "not_applicable", "introduction": "not_applicable",
                   "conclusion": "not_applicable", "references": "optional"},
    "web_page":   {"abstract": "optional", "introduction": "optional",
                   "conclusion": "optional", "references": "optional"},
    "collection": {"abstract": "not_applicable", "introduction": "not_applicable",
                   "conclusion": "not_applicable", "references": "not_applicable"},
}

HEADING_VOCABULARY = {
    "abstract": ("abstract", "summary", "resumen", "resume", "zusammenfassung",
                 "sommario"),
    "introduction": ("introduction", "introduccion", "einleitung", "einfuhrung",
                     "motivation and introduction", "background and introduction"),
    "conclusion": ("conclusion", "conclusions", "concluding remarks",
                   "discussion and conclusions", "conclusions and discussion",
                   "summary and conclusions", "discussion and conclusion",
                   "conclusiones", "schluss", "final remarks"),
    "references": ("references", "reference", "bibliography", "works cited",
                   "literature cited", "referencias", "bibliografia", "literatur"),
}

CONFIDENCE = {
    "semantic-markup": 0.95,
    "citation-meta": 0.98,
    "heading-vocabulary": 0.88,
    "numbered-heading": 0.85,
    "container-class": 0.9,
    "shape-heuristic": 0.55,
    "first-line": 0.45,
}

_NUMBERED = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+(\S.{0,110})$")
_ALL_CAPS = re.compile(r"^[A-Z][A-Z0-9 ,.\-:'()]{3,80}$")


def vocabulary_role(title: str) -> str | None:
    key = util.normalize_for_match(title)
    key = re.sub(r"^\d+(\s+\d+)*\s*", "", key).strip()
    for role, terms in HEADING_VOCABULARY.items():
        if key in terms:
            return role
    for role, terms in HEADING_VOCABULARY.items():
        for term in terms:
            if key.startswith(term + " ") or key == term:
                return role
    return None


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------


def normalize_conservative(raw: str) -> str:
    """NFC, uniform line endings, trimmed trailing spaces. Offsets stay usable.

    Deliberately does not join hyphenated line breaks: that is a lossy edit, so
    it happens in a separate layer that records where each join was made.
    """
    text = unicodedata.normalize("NFC", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("­", "")          # soft hyphen carries no content
    text = re.sub(r"[ \t]+(\n)", r"\1", text)
    return text


_HYPHEN_BREAK = re.compile(r"(\w)[‐-]\n(\w)")


def dehyphenate_with_map(text: str) -> tuple[str, list[dict]]:
    """Join words broken across lines, recording every join.

    Returns the joined text and a list of {at, original_start, original_end,
    joined} entries so any offset in the result can be translated back to the
    untouched layer, which is kept alongside it.
    """
    joins: list[dict] = []
    out: list[str] = []
    cursor = 0
    for match in _HYPHEN_BREAK.finditer(text):
        out.append(text[cursor:match.start() + 1])
        position = sum(len(p) for p in out)
        joins.append({
            "at": position,
            "original_start": match.start() + 1,
            "original_end": match.end() - 1,
            "removed": text[match.start() + 1:match.end() - 1],
        })
        cursor = match.end() - 1
    out.append(text[cursor:])
    return "".join(out), joins


# ---------------------------------------------------------------------------
# Headings
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Heading:
    title: str
    level: int
    start: int
    end: int
    number: str | None
    method: str
    confidence: float

    def as_dict(self) -> dict:
        return {"title": self.title, "level": self.level, "number": self.number,
                "char_start": self.start, "char_end": self.end,
                "method": self.method, "confidence": round(self.confidence, 2)}


def headings_from_blocks(blocks: list[extract_html.Block]) -> list[Heading]:
    """Semantic markup is authoritative; no guessing is needed."""
    out = []
    for block in blocks:
        if block.kind != "heading":
            continue
        match = _NUMBERED.match(block.text)
        number, title = (match.group(1), match.group(2)) if match else (None, block.text)
        out.append(Heading(title=title.strip(), level=block.level, start=block.start,
                           end=block.end, number=number, method="semantic-markup",
                           confidence=CONFIDENCE["semantic-markup"]))
    return out


def headings_from_text(text: str) -> list[Heading]:
    """Numbered patterns, a controlled vocabulary, then line shape.

    Shape alone is the weakest signal and is scored accordingly, so a work page
    can show how much to trust each boundary.
    """
    out: list[Heading] = []
    offset = 0
    lines = text.split("\n")
    for index, line in enumerate(lines):
        start = offset
        offset += len(line) + 1
        stripped = line.strip()
        if not stripped or len(stripped) > 120:
            continue
        before_blank = index == 0 or not lines[index - 1].strip()
        after_blank = index + 1 >= len(lines) or not lines[index + 1].strip()

        match = _NUMBERED.match(stripped)
        role = vocabulary_role(stripped)
        if match and (before_blank or after_blank) and not stripped.endswith("."):
            number = match.group(1)
            out.append(Heading(match.group(2).strip(), number.count(".") + 1,
                               start, start + len(line), number,
                               "numbered-heading", CONFIDENCE["numbered-heading"]))
        elif role and len(stripped) <= 60:
            out.append(Heading(stripped, 1, start, start + len(line), None,
                               "heading-vocabulary", CONFIDENCE["heading-vocabulary"]))
        elif (before_blank and after_blank and len(stripped) <= 80
              and not stripped.endswith((".", ",", ";"))
              and (_ALL_CAPS.match(stripped) or stripped.istitle())):
            out.append(Heading(stripped, 1, start, start + len(line), None,
                               "shape-heuristic", CONFIDENCE["shape-heuristic"]))
    return out


def section_tree(headings: list[Heading]) -> list[dict]:
    """Level-aware tree, flattened with an explicit level on each entry."""
    rows = []
    for heading in headings:
        row = heading.as_dict()
        row["level"] = heading.level
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------


def field(status: str, text: str | None = None, *, method: str | None = None,
          confidence: float | None = None, source: dict | None = None,
          reason: str | None = None, warnings: list[str] | None = None) -> dict:
    return {
        "status": status,
        "text": text,
        "source": source,
        "method": method,
        "confidence": confidence,
        "reason": reason,
        "warnings": list(warnings or []),
        "review": "unreviewed",
    }


def _slice_between(text: str, headings: list[Heading], index: int) -> tuple[str, int, int]:
    start = headings[index].end
    end = headings[index + 1].start if index + 1 < len(headings) else len(text)
    return text[start:end].strip(), start, end


def locate_role(role: str, text: str, headings: list[Heading],
                blocks: list[extract_html.Block], source: dict) -> dict:
    """Semantic container first, then heading vocabulary. Never a bare guess."""
    for block in blocks:
        if block.container and role in block.container and block.kind == "text":
            return field("present", block.text, method=f"container:{block.container}",
                         confidence=CONFIDENCE["container-class"],
                         source={**source, "chars": [block.start, block.end]})

    for index, heading in enumerate(headings):
        if vocabulary_role(heading.title) != role:
            continue
        body, start, end = _slice_between(text, headings, index)
        if not body:
            continue
        warnings = []
        matched = util.normalize_for_match(heading.title)
        if role == "conclusion" and "discussion" in matched:
            warnings.append(
                f"'{heading.title}' satisfies the conclusion role; it is a combined "
                "heading, not a dedicated conclusions section")
        return field("present", body, method=f"heading:{heading.title}",
                     confidence=heading.confidence,
                     source={**source, "chars": [start, end]}, warnings=warnings)
    return field("not_present", reason=f"no {role} heading or container was found")


def apply_expectation(role: str, located: dict, work_type: str) -> dict:
    """Turn a miss into the right state for this kind of document."""
    expectation = EXPECTATIONS.get(work_type, EXPECTATIONS["article"]).get(role, "optional")
    if located["status"] == "present":
        return located
    if expectation == "not_applicable":
        return field("not_applicable",
                     reason=f"a {work_type} is not expected to have a {role}")
    if expectation == "optional":
        return field("not_present",
                     reason=f"no {role} found; a {work_type} may legitimately lack one")
    located["reason"] = (located.get("reason") or "") + \
        f"; a {work_type} is normally expected to have a {role}"
    return located


def locate_title(parsed_meta: dict, headings: list[Heading], text: str,
                 work: Work, source: dict) -> dict:
    """Document evidence first, then compared with the manifest. Never replaced."""
    warnings: list[str] = []
    candidate = parsed_meta.get("title")
    method, confidence = "citation-meta", CONFIDENCE["citation-meta"]
    if not candidate and headings:
        candidate = headings[0].title
        method, confidence = "first-heading", headings[0].confidence
    if not candidate:
        first = next((l.strip() for l in text.split("\n") if l.strip()), "")
        candidate = first[:200] or None
        method, confidence = "first-line", CONFIDENCE["first-line"]
    if not candidate:
        return field("not_present", reason="no title evidence in the document")

    if work.title and util.normalize_for_match(work.title) != util.normalize_for_match(candidate):
        warnings.append(
            f"document title {candidate!r} differs from the manifest title "
            f"{work.title!r}; the manifest has not been overwritten")
    return field("present", candidate, method=method, confidence=confidence,
                 source=source, warnings=warnings)


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

_REF_MARKER = re.compile(r"^\s*(?:\[(\d{1,3})\]|\((\d{1,3})\)|(\d{1,3})\.)\s+(?=\S)")


def segment_references(block_text: str, blocks: list[extract_html.Block],
                       offset_base: int = 0) -> list[dict]:
    """Split a bibliography into raw entries. Resolution happens later.

    The raw string is always kept: a missing edge is visible, but a silently
    mangled reference corrupts everything downstream.
    """
    items = [b for b in blocks if b.kind == "list_item" and b.container
             and "ref" in (b.container or "")]
    if items:
        return [{"index": i, "raw": b.text, "char_start": b.start, "char_end": b.end,
                 "method": "list-item"} for i, b in enumerate(items, start=1)]

    if not block_text.strip():
        return []

    lines = block_text.split("\n")
    # Decide the style once for the whole section. Mixing per-line guesses is
    # what makes reference splitting fail on wrapped entries.
    marked_style = any(_REF_MARKER.match(line) for line in lines)
    method = "numbered-marker" if marked_style else "hanging-indent"

    entries: list[dict] = []
    current: list[str] = []
    start = offset_base
    cursor = offset_base

    def flush(end: int) -> None:
        raw = util.normalize_text(" ".join(current))
        if raw:
            entries.append({"index": len(entries) + 1, "raw": raw,
                            "char_start": start, "char_end": end, "method": method})

    for line in lines:
        line_len = len(line) + 1
        stripped = line.strip()
        if not stripped:
            if current:
                flush(cursor)
                current = []
            cursor += line_len
            continue
        # In numbered style a marker starts an entry; in hanging-indent style a
        # flush-left line does, and an indented line continues the one above.
        starts_entry = (_REF_MARKER.match(line) if marked_style
                        else not line.startswith((" ", "\t")))
        if starts_entry and current:
            flush(cursor)
            current = []
        if not current:
            start = cursor
        current.append(stripped)
        cursor += line_len
    if current:
        flush(cursor)
    return entries


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------

STATUS_EXTRACTED = "extracted"
STATUS_PARTIAL = "partial"
STATUS_MANUAL_REQUIRED = "manual_required"
STATUS_UNSUPPORTED = "unsupported"
STATUS_FAILED = "failed"
STATUS_NOT_ACQUIRED = "not_acquired"


def choose_asset(work: Work, artifacts: dict[str, dict]) -> dict | None:
    """Pick the best verified artifact for this work.

    Keyed on work_id rather than on the declared asset list, so a manually
    imported copy or an artifact recorded under another id is still found
    instead of the work silently looking unacquired.
    """
    declared = {a.id for a in work.assets}
    rows = [r for r in artifacts.values()
            if r["status"] == "downloaded"
            and (r["work_id"] == work.id or r["asset_id"] in declared)]
    if not rows:
        return None
    # Full text first, then a declared asset over an incidental one.
    rows.sort(key=lambda r: (0 if r["role"] == "fulltext" else 1,
                             0 if r["asset_id"] in declared else 1,
                             r["asset_id"]))
    return rows[0]


def extract_work(ws: Workspace, work: Work, artifacts: dict[str, dict],
                 pdf_timeout: float = 120.0) -> dict:
    """Extract one work into the document contract. Always returns a document."""
    document = {
        "schema_version": util.SCHEMA_VERSION,
        "work_id": work.id,
        "alias": work.primary_alias,
        "work_type": work.work_type,
        "adapter": "none",
        "overall_status": STATUS_NOT_ACQUIRED,
        "source": None,
        "fields": {},
        "sections": [],
        "raw_references": [],
        "warnings": [],
        "hyphen_joins": [],
        "publishable": {name: False for name in FIELD_NAMES},
    }

    if work.work_type == "collection":
        document["overall_status"] = "not_applicable"
        document["fields"] = {
            name: field("not_applicable",
                        reason="a collection holds no text of its own; see its members")
            for name in FIELD_NAMES}
        return document

    row = choose_asset(work, artifacts)
    if row is None:
        document["fields"] = {
            name: field("manual_required",
                        reason="no verified local artifact exists for this work")
            for name in FIELD_NAMES}
        document["warnings"].append(
            "nothing has been acquired for this work, so nothing was extracted")
        document["overall_status"] = STATUS_MANUAL_REQUIRED
        return document

    path = Path(row["path"])
    if not path.is_absolute():
        path = ws.root / path
    if not path.exists():
        return _fail(document, f"recorded artifact is missing from disk: {row['path']}")
    # The hash is verified against acquisition state before anything is parsed.
    actual = util.sha256_file(path)
    if row["sha256"] and actual != row["sha256"]:
        return _fail(document,
                     f"hash drift: ledger records {row['sha256'][:12]}, file is "
                     f"{actual[:12]}; refusing to extract from an unverified byte stream")

    source = {"asset_id": row["asset_id"], "asset_sha256": actual,
              "path": row["path"], "pages": None}
    document["source"] = source
    media = (row["media_type"] or "").lower()

    if "pdf" in media or path.suffix.lower() == ".pdf":
        return _extract_pdf(ws, document, work, path, source, pdf_timeout)
    if path.suffix.lower() == ".txt" or "text/plain" in media:
        return _extract_plaintext(ws, document, work, path, source)
    return _extract_markup(ws, document, work, path, source)


def _fail(document: dict, reason: str) -> dict:
    document["overall_status"] = STATUS_FAILED
    document["warnings"].append(reason)
    document["fields"] = {name: field("failed", reason=reason) for name in FIELD_NAMES}
    return document


def _store_text_layers(ws: Workspace, work: Work, raw: str) -> tuple[str, list[dict]]:
    """Keep the untouched layer on disk; return the normalised one plus joins."""
    normalized = normalize_conservative(raw)
    joined, joins = dehyphenate_with_map(normalized)
    directory = ws.text / util.safe_path_segment(work.primary_alias)
    util.write_text_atomic(directory / "raw.txt", raw)
    util.write_text_atomic(directory / "normalized.txt", normalized)
    util.write_text_atomic(directory / "dehyphenated.txt", joined)
    return normalized, joins


def _extract_markup(ws: Workspace, document: dict, work: Work, path: Path,
                    source: dict) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace")
    parsed = extract_html.parse_jats(raw)
    document["adapter"] = "jats" if parsed else "html"
    if parsed is None:
        parsed = extract_html.parse_html(raw)
    document["warnings"] += parsed.warnings

    text, joins = _store_text_layers(ws, work, parsed.text)
    document["hyphen_joins"] = joins
    meta = extract_html.citation_metadata(parsed)
    headings = headings_from_blocks(parsed.blocks)
    if not headings:
        headings = headings_from_text(text)
        document["warnings"].append(
            "no semantic heading tag was present; headings fall back to text shape")
    return _assemble(document, work, text, headings, parsed.blocks, meta, source)


def _extract_plaintext(ws: Workspace, document: dict, work: Work, path: Path,
                       source: dict) -> dict:
    document["adapter"] = "plaintext"
    raw = path.read_text(encoding="utf-8", errors="replace")
    pages = raw.count(extract_pdf.PAGE_BREAK) + 1
    source["pages"] = pages
    text, joins = _store_text_layers(ws, work, raw.replace(extract_pdf.PAGE_BREAK, "\n"))
    document["hyphen_joins"] = joins
    sidecar = path.with_suffix(".meta.json")
    meta = util.read_json(sidecar) if sidecar.exists() else {}
    return _assemble(document, work, text, headings_from_text(text), [], meta, source)


def _extract_pdf(ws: Workspace, document: dict, work: Work, path: Path,
                 source: dict, timeout: float) -> dict:
    document["adapter"] = "pdftotext"
    try:
        result = extract_pdf.extract(path, timeout=timeout)
    except extract_pdf.PdfUnsupported:
        reason = extract_pdf.unavailable_reason()
        document["adapter"] = "none"
        document["overall_status"] = STATUS_UNSUPPORTED
        document["warnings"].append(reason)
        document["fields"] = {name: field("manual_required", reason=reason)
                              for name in FIELD_NAMES}
        return document
    except extract_pdf.PdfExtractionFailed as exc:
        return _fail(document, f"{exc}: {exc.stderr[:400]}")

    document["warnings"] += result.warnings
    source["pages"] = result.pages
    if result.looks_scanned:
        document["overall_status"] = STATUS_MANUAL_REQUIRED
        document["fields"] = {
            name: field("manual_required",
                        reason="image-only PDF: OCR is a separate opt-in adapter")
            for name in FIELD_NAMES}
        return document

    text, joins = _store_text_layers(ws, work, result.text)
    document["hyphen_joins"] = joins
    if result.layout_text:
        util.write_text_atomic(
            ws.text / util.safe_path_segment(work.primary_alias) / "layout.txt",
            result.layout_text)
    return _assemble(document, work, text, headings_from_text(text), [], {}, source)


def _assemble(document: dict, work: Work, text: str, headings: list[Heading],
              blocks: list[extract_html.Block], meta: dict, source: dict) -> dict:
    document["sections"] = section_tree(headings)
    document["fields"]["title"] = locate_title(meta, headings, text, work, source)

    for role in ("abstract", "introduction", "conclusion"):
        located = locate_role(role, text, headings, blocks, source)
        document["fields"][role] = apply_expectation(role, located, work.work_type)

    references = locate_role("references", text, headings, blocks, source)
    references = apply_expectation("references", references, work.work_type)
    document["fields"]["references"] = references
    if references["status"] == "present":
        base = (references.get("source") or {}).get("chars", [0, 0])[0]
        document["raw_references"] = segment_references(
            references["text"] or "", blocks, offset_base=base)
        if not document["raw_references"]:
            references["warnings"].append(
                "a references section was found but no entry could be segmented")

    present = [n for n in FIELD_NAMES if document["fields"][n]["status"] == "present"]
    applicable = [n for n in FIELD_NAMES
                  if document["fields"][n]["status"] != "not_applicable"]
    document["overall_status"] = (
        STATUS_EXTRACTED if len(present) == len(applicable) else
        STATUS_PARTIAL if present else STATUS_MANUAL_REQUIRED)

    document["publishable"] = {
        "title": work.rights.publish_metadata,
        "abstract": work.rights.publish_abstract,
        "introduction": work.rights.publish_fulltext,
        "conclusion": work.rights.publish_fulltext,
        "references": work.rights.publish_metadata,
    }
    return document


def extract_corpus(ws: Workspace, corpus: Corpus, store: Store,
                   aliases: list[str] | None = None,
                   pdf_timeout: float = 120.0) -> list[dict]:
    artifacts = {row["asset_id"]: row for row in store.artifacts()}
    selected = set(aliases) if aliases else None
    documents = []
    ws.documents.mkdir(parents=True, exist_ok=True)
    for work in corpus.works:
        if selected and not (set(work.aliases) & selected):
            continue
        document = extract_work(ws, work, artifacts, pdf_timeout=pdf_timeout)
        util.write_json_atomic(
            ws.documents / f"{util.safe_path_segment(work.primary_alias)}.json", document)
        documents.append(document)
    return documents


def summarize(documents: list[dict]) -> dict:
    counts: dict[str, int] = {}
    field_states: dict[str, dict[str, int]] = {n: {} for n in FIELD_NAMES}
    for document in documents:
        counts[document["overall_status"]] = counts.get(document["overall_status"], 0) + 1
        for name in FIELD_NAMES:
            status = document["fields"].get(name, {}).get("status", "missing")
            field_states[name][status] = field_states[name].get(status, 0) + 1
    return {
        "counts": dict(sorted(counts.items())),
        "field_states": {k: dict(sorted(v.items())) for k, v in field_states.items()},
        "references_found": sum(len(d["raw_references"]) for d in documents),
        "manual_queue": sorted(d["alias"] for d in documents
                               if d["overall_status"] in (STATUS_MANUAL_REQUIRED,
                                                          STATUS_UNSUPPORTED)),
        "failed": sorted(d["alias"] for d in documents
                         if d["overall_status"] == STATUS_FAILED),
    }


def exit_code_for(documents: list[dict], strict: bool = False) -> int:
    summary = summarize(documents)
    codes = []
    if summary["failed"]:
        codes.append(util.EXIT_INTEGRITY)
    if strict and summary["manual_queue"]:
        codes.append(util.EXIT_INCOMPLETE)
    return util.resolve_exit_code(codes)
