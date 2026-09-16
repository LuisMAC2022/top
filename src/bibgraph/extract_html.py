"""HTML / JATS / XML adapter, standard library only.

Semantic markup and citation metadata are trusted before heuristics. Scripts,
styles, navigation and repeated chrome are removed. Every emitted block keeps
its character span in the extracted text so a passage can be traced back.
"""

from __future__ import annotations

import dataclasses
import html.parser
import re
import xml.etree.ElementTree as ET

from . import util

DROP_TAGS = {"script", "style", "noscript", "nav", "header", "footer", "aside",
             "form", "button", "svg", "iframe", "template"}
BLOCK_TAGS = {"p", "div", "section", "article", "li", "tr", "br", "blockquote",
              "figcaption", "dd", "dt", "pre", "h1", "h2", "h3", "h4", "h5", "h6"}
HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}

CITATION_META = {
    "citation_title": "title",
    "dc.title": "title",
    "citation_doi": "doi",
    "dc.identifier": "doi",
    "citation_publication_date": "date",
    "citation_date": "date",
    "citation_year": "year",
}


@dataclasses.dataclass
class Block:
    kind: str            # "heading" | "text" | "list_item"
    text: str
    level: int = 0
    start: int = 0
    end: int = 0
    container: str | None = None   # nearest ancestor class/id, when meaningful


@dataclasses.dataclass
class ParsedHtml:
    text: str
    blocks: list[Block]
    meta: dict[str, list[str]]
    title_tag: str | None
    warnings: list[str]


class _Extractor(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.blocks: list[Block] = []
        self.meta: dict[str, list[str]] = {}
        self.title_tag: str | None = None
        self.warnings: list[str] = []
        self._drop_depth = 0
        self._stack: list[tuple[str, str | None]] = []
        self._buffer: list[str] = []
        self._buffer_kind = "text"
        self._buffer_level = 0
        self._in_title = False

    # -- offsets -----------------------------------------------------------

    @property
    def _position(self) -> int:
        return sum(len(p) for p in self.parts)

    def _flush(self) -> None:
        text = util.normalize_text("".join(self._buffer))
        self._buffer = []
        if not text:
            self._buffer_kind, self._buffer_level = "text", 0
            return
        start = self._position
        self.parts.append(text + "\n")
        container = next((c for _t, c in reversed(self._stack) if c), None)
        self.blocks.append(Block(kind=self._buffer_kind, text=text,
                                 level=self._buffer_level, start=start,
                                 end=start + len(text), container=container))
        self._buffer_kind, self._buffer_level = "text", 0

    # -- parsing -----------------------------------------------------------

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "meta":
            name = (attributes.get("name") or attributes.get("property") or "").lower()
            content = attributes.get("content")
            if name and content:
                self.meta.setdefault(name, []).append(util.normalize_text(content))
            return
        if tag in DROP_TAGS:
            self._drop_depth += 1
            return
        if self._drop_depth:
            return
        if tag == "title":
            self._in_title = True
            return
        marker = attributes.get("class") or attributes.get("id")
        self._stack.append((tag, (marker or "").lower() or None))
        if tag in BLOCK_TAGS:
            self._flush()
        if tag in HEADING_TAGS:
            self._buffer_kind = "heading"
            self._buffer_level = HEADING_TAGS[tag]
        elif tag == "li":
            self._buffer_kind = "list_item"

    def handle_endtag(self, tag):
        if tag in DROP_TAGS:
            self._drop_depth = max(0, self._drop_depth - 1)
            return
        if self._drop_depth:
            return
        if tag == "title":
            self._in_title = False
            return
        if tag in BLOCK_TAGS:
            self._flush()
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data):
        if self._in_title:
            self.title_tag = util.normalize_text((self.title_tag or "") + data)
            return
        if self._drop_depth:
            return
        self._buffer.append(data)

    def close(self):
        super().close()
        self._flush()


def parse_html(source: str) -> ParsedHtml:
    extractor = _Extractor()
    try:
        extractor.feed(source)
        extractor.close()
    except AssertionError as exc:  # malformed markup can trip the parser
        extractor.warnings.append(f"HTML parser aborted: {exc}")
    return ParsedHtml(
        text="".join(extractor.parts),
        blocks=extractor.blocks,
        meta=extractor.meta,
        title_tag=extractor.title_tag,
        warnings=extractor.warnings,
    )


def parse_jats(source: str) -> ParsedHtml | None:
    """JATS/XML article bodies, when the document really is JATS."""
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        return None
    if not root.tag.endswith("article"):
        return None

    parts: list[str] = []
    blocks: list[Block] = []
    warnings: list[str] = []

    def localname(element) -> str:
        return element.tag.rsplit("}", 1)[-1]

    def emit(kind: str, text: str, level: int = 0, container: str | None = None) -> None:
        text = util.normalize_text(text)
        if not text:
            return
        start = sum(len(p) for p in parts)
        parts.append(text + "\n")
        blocks.append(Block(kind=kind, text=text, level=level, start=start,
                            end=start + len(text), container=container))

    title_element = root.find(".//{*}article-title")
    title = "".join(title_element.itertext()) if title_element is not None else None
    if title:
        emit("heading", title, 1, "article-title")

    abstract = root.find(".//{*}abstract")
    if abstract is not None:
        emit("heading", "Abstract", 2, "abstract")
        for paragraph in abstract.iter():
            if localname(paragraph) == "p":
                emit("text", "".join(paragraph.itertext()), container="abstract")

    body = root.find(".//{*}body")
    if body is not None:
        for section in body.iter():
            name = localname(section)
            if name == "title":
                emit("heading", "".join(section.itertext()), 2, "body")
            elif name == "p":
                emit("text", "".join(section.itertext()), container="body")

    references = root.find(".//{*}ref-list")
    if references is not None:
        emit("heading", "References", 2, "ref-list")
        for ref in references.iter():
            if localname(ref) == "ref":
                emit("list_item", " ".join("".join(ref.itertext()).split()),
                     container="ref-list")

    meta: dict[str, list[str]] = {}
    if title:
        meta["citation_title"] = [util.normalize_text(title)]
    doi = root.find(".//{*}article-id[@pub-id-type='doi']")
    if doi is not None and doi.text:
        meta["citation_doi"] = [doi.text.strip()]

    return ParsedHtml(text="".join(parts), blocks=blocks, meta=meta,
                      title_tag=title, warnings=warnings)


def citation_metadata(parsed: ParsedHtml) -> dict:
    """Pull citation_* / Dublin Core metadata, which beats any heuristic."""
    out: dict[str, object] = {}
    for key, values in parsed.meta.items():
        target = CITATION_META.get(key)
        if target and values and target not in out:
            out[target] = values[0]
    authors = parsed.meta.get("citation_author") or parsed.meta.get("dc.creator")
    if authors:
        out["authors"] = list(authors)
    year = out.get("year")
    date = out.get("date")
    if not year and isinstance(date, str):
        match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", date)
        if match:
            out["year"] = match.group(1)
    return out
