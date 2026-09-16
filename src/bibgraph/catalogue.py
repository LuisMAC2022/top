"""One-purpose importer for the access-verification Markdown catalogue.

Deliberately not a general Markdown parser. It understands exactly one table
shape and refuses anything else with a message naming the columns it found and
the columns it needs, so a changed catalogue is a visible error rather than a
silently half-imported corpus.

Rows are keyed by the alias column, so one intellectual work may span several
rows: each row contributes one asset (landing page, full text, mirror, ...).
"""

from __future__ import annotations

import re
from pathlib import Path

from . import util
from .model import (
    ACCESS_STATES,
    ACQUISITION_INTENTS,
    ASSET_ROLES,
    WORK_TYPES,
    ValidationError,
)

REQUIRED_COLUMNS = ("id", "title", "type", "access", "url", "role", "intent")
OPTIONAL_COLUMNS = (
    "authors", "year", "license", "license evidence", "observed",
    "notes", "container", "members",
)

_MD_LINK = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
_BARE_URL = re.compile(r"https?://[^\s<>\]\)]+")


class CatalogueError(ValidationError):
    pass


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    # Pipes inside inline code or links are not part of this table shape.
    return [cell.strip() for cell in line.split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c != "")


def extract_url(cell: str) -> str | None:
    match = _MD_LINK.search(cell or "")
    if match:
        return match.group("url").strip()
    match = _BARE_URL.search(cell or "")
    return match.group(0).rstrip(".,;") if match else None


def strip_markdown(cell: str) -> str:
    text = _MD_LINK.sub(lambda m: m.group("text"), cell or "")
    text = re.sub(r"[*_`]", "", text)
    return util.normalize_text(text)


def find_table(text: str) -> list[list[str]]:
    """Return the first pipe table whose header carries every required column."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if "|" not in line:
            continue
        header = [c.lower() for c in _split_row(line)]
        if not set(REQUIRED_COLUMNS).issubset(set(header)):
            continue
        if index + 1 >= len(lines) or not _is_separator(_split_row(lines[index + 1])):
            continue
        rows = [header]
        for body in lines[index + 2:]:
            if "|" not in body or not body.strip():
                break
            rows.append(_split_row(body))
        return rows
    raise CatalogueError(
        "no catalogue table found. This importer handles exactly one table shape "
        "and needs a header row containing every one of these columns: "
        + ", ".join(REQUIRED_COLUMNS)
        + ". Optional columns: " + ", ".join(OPTIONAL_COLUMNS) + "."
    )


def _cell(row: list[str], header: list[str], name: str) -> str:
    if name not in header:
        return ""
    index = header.index(name)
    return row[index] if index < len(row) else ""


def _coerce(value: str, allowed: tuple[str, ...], default: str, where: str, field: str) -> str:
    token = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not token:
        return default
    if token not in allowed:
        raise CatalogueError(
            f"{where}: {field}={value!r} is not one of {', '.join(allowed)}"
        )
    return token


def import_catalogue(path: Path, observed_on: str | None = None) -> dict:
    """Parse the catalogue into a corpus.json structure. Never invents values."""
    text = Path(path).read_text(encoding="utf-8")
    rows = find_table(text)
    header, body = rows[0], rows[1:]

    works: dict[str, dict] = {}
    order: list[str] = []
    asset_counter: dict[str, int] = {}

    for line_no, row in enumerate(body, start=1):
        alias = strip_markdown(_cell(row, header, "id"))
        if not alias:
            continue
        where = f"{Path(path).name} row {line_no} ({alias})"
        title = strip_markdown(_cell(row, header, "title"))
        work_type = _coerce(_cell(row, header, "type"), WORK_TYPES, "article", where, "type")
        access = _coerce(_cell(row, header, "access"), ACCESS_STATES, "unknown", where, "access")

        if alias not in works:
            order.append(alias)
            members = [
                m.strip() for m in strip_markdown(_cell(row, header, "members")).split(",")
                if m.strip()
            ]
            container = strip_markdown(_cell(row, header, "container")) or None
            year_raw = strip_markdown(_cell(row, header, "year"))
            authors = [
                a.strip() for a in strip_markdown(_cell(row, header, "authors")).split(";")
                if a.strip()
            ]
            license_name = strip_markdown(_cell(row, header, "license")) or None
            evidence = extract_url(_cell(row, header, "license evidence"))
            works[alias] = {
                "id": util.local_id(f"{'; '.join(authors)}|{title}|{year_raw}" if title else f"seed-alias:{alias}"),
                "aliases": [alias],
                "title": title,
                "title_status": "present" if title else "unknown",
                "authors": authors,
                "year": int(year_raw) if re.fullmatch(r"\d{4}", year_raw or "") else None,
                "work_type": work_type,
                "metadata_status": "verified" if title else "unverified",
                "container": container,
                "members": members,
                "rights": {
                    "access": access,
                    "license": license_name,
                    "license_evidence_url": evidence,
                    # Open access is not redistribution permission. Publication
                    # stays off until a human records licence evidence.
                    "local_storage_allowed": access == "open",
                    "publish_metadata": True,
                    "publish_abstract": False,
                    "publish_fulltext": False,
                },
                "assets": [],
                "observations": [],
                "note": strip_markdown(_cell(row, header, "notes")) or None,
            }
            observation = strip_markdown(_cell(row, header, "observed"))
            if observation or observed_on:
                works[alias]["observations"].append({
                    "observed_on": observed_on,
                    "status": access,
                    "note": observation or None,
                })

        url = extract_url(_cell(row, header, "url"))
        role = _coerce(_cell(row, header, "role"), ASSET_ROLES, "landing", where, "role")
        intent = _coerce(_cell(row, header, "intent"), ACQUISITION_INTENTS, "metadata_only", where, "intent")
        if url:
            asset_counter[alias] = asset_counter.get(alias, 0) + 1
            works[alias]["assets"].append({
                "id": f"{util.safe_path_segment(alias)}-{role}-{asset_counter[alias]}",
                "role": role,
                "url": url,
                "intent": intent,
                "expected_media_type": _guess_media_type(url),
                "note": None,
            })

    return {
        "schema_version": util.SCHEMA_VERSION,
        "source": {
            "document": Path(path).name,
            "supplied": True,
            "observed_on": observed_on,
            "note": "Imported from the access-verification catalogue. Access states are "
                    "observations on the recorded date, not permanent truths.",
        },
        "works": [works[a] for a in order],
    }


def _guess_media_type(url: str) -> str | None:
    lowered = url.lower().split("?", 1)[0]
    if lowered.endswith(".pdf"):
        return "application/pdf"
    if lowered.endswith((".htm", ".html")):
        return "text/html"
    if lowered.endswith(".txt"):
        return "text/plain"
    if lowered.endswith((".xml", ".jats")):
        return "application/xml"
    return None
