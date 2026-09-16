"""Parse raw bibliography entries into normalised candidate identities.

Nothing here decides that two works are the same; it only extracts and
normalises the evidence. The original string is always retained, because a
missing edge is visible while a mangled reference quietly corrupts everything
downstream.
"""

from __future__ import annotations

import dataclasses
import re

from . import util

# A DOI is 10.<registrant>/<suffix>; the suffix is deliberately permissive.
_DOI = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9<>\[\]]+", re.I)
_DOI_PREFIXES = re.compile(
    r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*|https?://doi\.org/)", re.I)
_URL = re.compile(r"https?://[^\s,;<>\"]+")
_ISBN = re.compile(r"\bISBN(?:-1[03])?:?\s*((?:97[89][- ]?)?[\d][-\d ]{8,}[\dXx])\b")
_BARE_ISBN = re.compile(r"\b((?:97[89][- ]?)?\d[-\d ]{8,}[\dXx])\b")
_YEAR = re.compile(r"\b(1[5-9]\d{2}|20\d{2})\b")
_VOLUME_PAGES = re.compile(r"\b(\d{1,4})\s*\(\s*(\d{1,3})\s*\)\s*:\s*(\d{1,5})\s*[-–]\s*(\d{1,5})")
_PAGES = re.compile(r"\b(\d{1,5})\s*[-–]{1,2}\s*(\d{1,5})\b")
_QUOTED = re.compile(r"[\"“]([^\"”]{8,300})[\"”]")
_LEADING_MARKER = re.compile(r"^\s*(?:\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}\.)\s*")
# Separators that may sit between two names in an author list.
_AUTHOR_SEP = re.compile(r"\s*(?:,\s*and\b|,|;|\band\b|&|\.)\s*", re.I)

# "P. Alexandroff", "Alexandroff, P.", "D. Kleitman and B. Rothschild"
_AUTHOR_INITIALS_FIRST = re.compile(
    r"\b((?:[A-Z]\.\s*){1,3}[A-Z][\w'À-ɏ-]+)")
_AUTHOR_LAST_FIRST = re.compile(
    r"\b([A-Z][\w'À-ɏ-]+),\s*((?:[A-Z]\.\s*){1,3})")


@dataclasses.dataclass
class ParsedReference:
    index: int
    raw: str
    doi: str | None = None
    url: str | None = None
    isbn: str | None = None
    year: int | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    title: str | None = None
    authors: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)

    @property
    def normalized_title(self) -> str:
        return util.normalize_for_match(self.title or "")

    @property
    def first_author_key(self) -> str:
        if not self.authors:
            return ""
        return util.normalize_for_match(surname(self.authors[0]))


def normalize_doi(value: str | None) -> str | None:
    """Lowercase, strip resolver prefixes and trailing punctuation.

    DOIs are case-insensitive for matching purposes, and the same DOI arrives
    as a bare string, a doi: prefix or a doi.org URL.
    """
    if not value:
        return None
    candidate = _DOI_PREFIXES.sub("", value.strip())
    match = _DOI.search(candidate)
    if not match:
        return None
    doi = match.group(0).rstrip(".,;:)]>”\"'")
    return doi.lower()


def normalize_isbn(value: str | None) -> str | None:
    """Strip separators, validate the checksum, and return ISBN-13."""
    if not value:
        return None
    digits = re.sub(r"[^0-9Xx]", "", value).upper()
    if len(digits) == 10:
        if not _isbn10_valid(digits):
            return None
        digits = _isbn10_to_13(digits)
    if len(digits) != 13 or not digits.isdigit():
        return None
    return digits if _isbn13_valid(digits) else None


def _isbn10_valid(value: str) -> bool:
    total = 0
    for index, char in enumerate(value):
        digit = 10 if char == "X" else (int(char) if char.isdigit() else -1)
        if digit < 0 or (char == "X" and index != 9):
            return False
        total += (10 - index) * digit
    return total % 11 == 0


def _isbn10_to_13(value: str) -> str:
    core = "978" + value[:9]
    checksum = (10 - sum((3 if i % 2 else 1) * int(c)
                         for i, c in enumerate(core)) % 10) % 10
    return core + str(checksum)


def _isbn13_valid(value: str) -> bool:
    return sum((3 if i % 2 else 1) * int(c) for i, c in enumerate(value)) % 10 == 0


def surname(author: str) -> str:
    author = author.strip().rstrip(".,;")
    if "," in author:
        return author.split(",", 1)[0].strip()
    parts = [p for p in author.split() if not re.fullmatch(r"[A-Z]\.?", p)]
    return parts[-1] if parts else author


def normalize_author(author: str) -> str:
    """'Alexandroff, P.' and 'P. Alexandroff' collapse to the same key."""
    author = util.normalize_text(author).rstrip(".,;")
    initials = re.findall(r"\b([A-Z])\.", author)
    if not initials:
        initials = [w[0] for w in author.split() if len(w) == 1 and w.isupper()]
    last = surname(author)
    key = util.normalize_for_match(last)
    return f"{key} {''.join(i.lower() for i in initials)}".strip()


def parse_reference(index: int, raw: str) -> ParsedReference:
    """Extract every identifier the string offers. Never rewrites the string."""
    text = util.normalize_text(raw)
    body = _LEADING_MARKER.sub("", text)
    parsed = ParsedReference(index=index, raw=raw)

    url_match = _URL.search(body)
    if url_match:
        parsed.url = url_match.group(0).rstrip(".,;)")
    parsed.doi = normalize_doi(body)
    if parsed.doi is None and parsed.url:
        parsed.doi = normalize_doi(parsed.url)

    isbn_match = _ISBN.search(body)
    if isbn_match:
        parsed.isbn = normalize_isbn(isbn_match.group(1))
        if parsed.isbn is None:
            parsed.warnings.append("an ISBN-shaped value failed its checksum")
    elif "isbn" in body.lower():
        bare = _BARE_ISBN.search(body)
        if bare:
            parsed.isbn = normalize_isbn(bare.group(1))


    # Identifiers are removed before volume/page/year detection, otherwise an
    # ISBN's digit groups are read as a page range.
    scrubbed = body
    for identifier in (parsed.url, isbn_match.group(0) if isbn_match else None):
        if identifier:
            scrubbed = scrubbed.replace(identifier, " ")
    scrubbed = _DOI.sub(" ", scrubbed)

    years = _YEAR.findall(scrubbed)
    if years:
        parsed.year = int(years[-1])

    volume_match = _VOLUME_PAGES.search(scrubbed)
    if volume_match:
        parsed.volume, parsed.issue = volume_match.group(1), volume_match.group(2)
        parsed.pages = f"{volume_match.group(3)}-{volume_match.group(4)}"
    else:
        pages_match = _PAGES.search(scrubbed)
        if pages_match and pages_match.group(0) != str(parsed.year or ""):
            parsed.pages = f"{pages_match.group(1)}-{pages_match.group(2)}"

    parsed.authors = _extract_authors(body)
    parsed.title = _extract_title(scrubbed, parsed)
    if not parsed.title:
        parsed.warnings.append("no title candidate could be isolated")
    return parsed


def _extract_authors(body: str) -> list[str]:
    """Walk the author list from the start, name by name.

    Splitting on "." first is what breaks multi-author strings: initials are
    full of periods, so "D. Kleitman and B. Rothschild" loses its second name
    and the title then starts one name too late.
    """
    authors: list[str] = []
    position = 0
    limit = min(len(body), 300)
    while position < limit:
        match = (_AUTHOR_LAST_FIRST.match(body, position)
                 or _AUTHOR_INITIALS_FIRST.match(body, position))
        if not match:
            break
        if match.re is _AUTHOR_LAST_FIRST:
            authors.append(f"{match.group(1)}, {match.group(2).strip()}")
        else:
            authors.append(match.group(1).strip())
        position = match.end()
        separator = _AUTHOR_SEP.match(body, position)
        if not separator:
            break
        position = separator.end()

    seen: set[str] = set()
    unique = []
    for author in authors:
        key = normalize_author(author)
        if key and key not in seen:
            seen.add(key)
            unique.append(util.normalize_text(author))
    return unique


def _extract_title(body: str, parsed: ParsedReference) -> str | None:
    """A conservative title candidate, or nothing.

    Quoted text is trusted. Otherwise the segment after the author list and
    before the venue is taken, which is right for the common styles and is
    scored low enough elsewhere that a wrong guess cannot auto-accept.
    """
    quoted = _QUOTED.search(body)
    if quoted:
        return util.normalize_text(quoted.group(1))

    working = body
    for author in parsed.authors:
        working = working.replace(author, "", 1)
    working = working.lstrip(" .,;and&")
    working = _DOI.sub("", _URL.sub("", working))

    segments = [s.strip() for s in re.split(r"(?<!\b[A-Z])\.\s+", working) if s.strip()]
    for segment in segments:
        cleaned = segment.strip(" .,;")
        if len(cleaned) < 8:
            continue
        if _YEAR.fullmatch(cleaned):
            continue
        # A venue segment usually carries volume/page numbers; a title rarely does.
        if re.search(r"\d{1,4}\s*[:(]\s*\d", cleaned):
            continue
        return util.normalize_text(cleaned)
    return None


def parse_all(entries: list[dict]) -> list[ParsedReference]:
    return [parse_reference(entry.get("index", i), entry["raw"])
            for i, entry in enumerate(entries, start=1)]
