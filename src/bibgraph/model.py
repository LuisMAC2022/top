"""Typed corpus + dependency-DAG model, and the validator that gates everything.

`config/corpus.json` and `config/dependencies.json` are the human-reviewed
source of truth. Nothing downstream is allowed to run against a manifest that
does not validate, so this module owns the vocabularies as well as the checks.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Iterable

from . import util

# ---------------------------------------------------------------------------
# Controlled vocabularies. Anything outside these is a validation error, never
# a silently accepted free-text value.
# ---------------------------------------------------------------------------

ASSET_ROLES = ("landing", "fulltext", "metadata", "mirror", "preview", "borrow")
ACQUISITION_INTENTS = ("required", "fallback", "metadata_only", "manual", "ignore")
ACCESS_STATES = (
    "open",
    "preview",
    "borrow",
    "purchase",
    "institutional",
    "unknown",
)
WORK_TYPES = ("article", "book", "notes", "sequence", "web_page", "collection")
NODE_KINDS = ("work", "choice", "collection")
EDGE_TYPES = (
    "prerequisite",
    "backup",
    "validates",
    "conditional",
    "orientation",
    "historical",
)
# Only these edge types constrain reading order, so only these must stay acyclic.
ORDERING_EDGE_TYPES = ("prerequisite", "conditional", "orientation", "historical")

FIELD_STATES = ("present", "not_present", "not_applicable", "manual_required", "failed")
METADATA_STATUSES = ("verified", "unverified")

# The 20 seed aliases the source catalogue is defined to contain.
SEED_ALIASES = (
    ["R0"]
    + [f"A{i}" for i in range(1, 8)]
    + [f"B{i}" for i in range(1, 7)]
    + [f"C{i}" for i in range(1, 6)]
    + ["D1"]
)


@dataclasses.dataclass(frozen=True)
class Issue:
    severity: str  # "error" | "warning"
    code: str
    message: str
    location: str = ""

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)

    def __str__(self) -> str:
        where = f" [{self.location}]" if self.location else ""
        return f"{self.severity.upper()} {self.code}{where}: {self.message}"


class ValidationError(Exception):
    """Raised when a manifest cannot even be structurally loaded."""


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Asset:
    id: str
    role: str
    url: str | None
    intent: str
    expected_media_type: str | None = None
    note: str | None = None

    @property
    def is_required(self) -> bool:
        return self.intent == "required"


@dataclasses.dataclass
class Rights:
    access: str = "unknown"
    license: str | None = None
    license_evidence_url: str | None = None
    local_storage_allowed: bool = False
    publish_metadata: bool = True
    publish_abstract: bool = False
    publish_fulltext: bool = False

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Rights":
        raw = dict(raw or {})
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})


@dataclasses.dataclass
class Work:
    id: str
    aliases: list[str]
    title: str
    title_status: str
    work_type: str
    metadata_status: str
    rights: Rights
    assets: list[Asset]
    authors: list[str] = dataclasses.field(default_factory=list)
    year: int | None = None
    container: str | None = None      # parent collection alias, e.g. A5 children
    members: list[str] = dataclasses.field(default_factory=list)
    observations: list[dict] = dataclasses.field(default_factory=list)
    note: str | None = None

    @property
    def primary_alias(self) -> str:
        return self.aliases[0] if self.aliases else self.id

    @property
    def display_title(self) -> str:
        if self.title_status == "present" and self.title:
            return self.title
        return f"{self.primary_alias} — title not supplied"


@dataclasses.dataclass
class Node:
    id: str            # alias-space identifier, e.g. "A5" or "choice:proof-foundation"
    kind: str
    label: str
    ref: str | None = None          # work id for kind == "work"/"collection"
    options: list[str] = dataclasses.field(default_factory=list)  # kind == "choice"
    note: str | None = None


@dataclasses.dataclass
class Edge:
    source: str        # the prerequisite
    target: str        # the dependent
    type: str
    note: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source, self.target, self.type)


@dataclasses.dataclass
class Corpus:
    source: dict
    works: list[Work]

    def by_alias(self) -> dict[str, Work]:
        index: dict[str, Work] = {}
        for work in self.works:
            for alias in work.aliases:
                index[alias] = work
        return index

    def by_id(self) -> dict[str, Work]:
        return {w.id: w for w in self.works}

    def all_aliases(self) -> list[str]:
        return sorted({a for w in self.works for a in w.aliases})

    @property
    def expected_aliases(self) -> list[str]:
        """Aliases the catalogue is contracted to contain.

        Defaults to this project's 20 seeds; a manifest may declare its own so
        that fixtures and future catalogues are checked against their own
        contract rather than a hardcoded one.
        """
        declared = self.source.get("expected_aliases")
        if isinstance(declared, list) and declared:
            return [str(a) for a in declared]
        return list(SEED_ALIASES)


@dataclasses.dataclass
class Dependencies:
    nodes: list[Node]
    edges: list[Edge]

    def node_ids(self) -> set[str]:
        return {n.id for n in self.nodes}

    def by_id(self) -> dict[str, Node]:
        return {n.id: n for n in self.nodes}

    def ordering_edges(self) -> list[Edge]:
        return [e for e in self.edges if e.type in ORDERING_EDGE_TYPES]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _require(raw: dict, key: str, where: str) -> Any:
    if key not in raw:
        raise ValidationError(f"{where}: missing required key {key!r}")
    return raw[key]


def load_corpus(path: Path) -> Corpus:
    raw = util.read_json(Path(path))
    if not isinstance(raw, dict):
        raise ValidationError("corpus.json must contain an object")
    works_raw = _require(raw, "works", "corpus.json")
    if not isinstance(works_raw, list):
        raise ValidationError("corpus.json: 'works' must be a list")

    works: list[Work] = []
    for index, item in enumerate(works_raw):
        where = f"corpus.works[{index}]"
        if not isinstance(item, dict):
            raise ValidationError(f"{where}: must be an object")
        assets = []
        for a_index, a_raw in enumerate(item.get("assets", []) or []):
            a_where = f"{where}.assets[{a_index}]"
            if not isinstance(a_raw, dict):
                raise ValidationError(f"{a_where}: must be an object")
            assets.append(
                Asset(
                    id=str(_require(a_raw, "id", a_where)),
                    role=str(_require(a_raw, "role", a_where)),
                    url=a_raw.get("url"),
                    intent=str(_require(a_raw, "intent", a_where)),
                    expected_media_type=a_raw.get("expected_media_type"),
                    note=a_raw.get("note"),
                )
            )
        works.append(
            Work(
                id=str(_require(item, "id", where)),
                aliases=[str(a) for a in item.get("aliases", []) or []],
                title=str(item.get("title") or ""),
                title_status=str(item.get("title_status") or "unknown"),
                work_type=str(_require(item, "work_type", where)),
                metadata_status=str(item.get("metadata_status") or "unverified"),
                rights=Rights.from_dict(item.get("rights")),
                assets=assets,
                authors=[str(a) for a in item.get("authors", []) or []],
                year=item.get("year"),
                container=item.get("container"),
                members=[str(m) for m in item.get("members", []) or []],
                observations=list(item.get("observations", []) or []),
                note=item.get("note"),
            )
        )
    return Corpus(source=dict(raw.get("source") or {}), works=works)


def load_dependencies(path: Path) -> Dependencies:
    raw = util.read_json(Path(path))
    if not isinstance(raw, dict):
        raise ValidationError("dependencies.json must contain an object")

    nodes = []
    for index, item in enumerate(_require(raw, "nodes", "dependencies.json")):
        where = f"dependencies.nodes[{index}]"
        if not isinstance(item, dict):
            raise ValidationError(f"{where}: must be an object")
        nodes.append(
            Node(
                id=str(_require(item, "id", where)),
                kind=str(_require(item, "kind", where)),
                label=str(item.get("label") or item["id"]),
                ref=item.get("ref"),
                options=[str(o) for o in item.get("options", []) or []],
                note=item.get("note"),
            )
        )

    edges = []
    for index, item in enumerate(raw.get("edges", []) or []):
        where = f"dependencies.edges[{index}]"
        if not isinstance(item, dict):
            raise ValidationError(f"{where}: must be an object")
        edges.append(
            Edge(
                source=str(_require(item, "from", where)),
                target=str(_require(item, "to", where)),
                type=str(_require(item, "type", where)),
                note=item.get("note"),
            )
        )
    return Dependencies(nodes=nodes, edges=edges)


def load_reading_profile(path: Path) -> dict[str, str | None]:
    raw = util.read_json(Path(path))
    selections = raw.get("selections") or {}
    if not isinstance(selections, dict):
        raise ValidationError("reading-profile.json: 'selections' must be an object")
    return {str(k): (str(v) if v is not None else None) for k, v in selections.items()}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(
    corpus: Corpus,
    deps: Dependencies,
    profile: dict[str, str | None] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    issues += _validate_corpus(corpus)
    issues += _validate_dependencies(corpus, deps)
    issues += _validate_choices(deps, profile or {})
    return issues


def _validate_corpus(corpus: Corpus) -> list[Issue]:
    issues: list[Issue] = []
    seen_ids: set[str] = set()
    seen_aliases: dict[str, str] = {}
    seen_asset_ids: set[str] = set()
    seen_urls: dict[str, str] = {}

    for work in corpus.works:
        where = work.primary_alias
        if work.id in seen_ids:
            issues.append(Issue("error", "duplicate-work-id", f"duplicate work id {work.id}", where))
        seen_ids.add(work.id)

        if not work.aliases:
            issues.append(Issue("error", "missing-alias", "work has no alias", work.id))
        for alias in work.aliases:
            if alias in seen_aliases:
                issues.append(
                    Issue("error", "duplicate-alias", f"alias {alias} also used by {seen_aliases[alias]}", where)
                )
            seen_aliases[alias] = work.id

        if work.work_type not in WORK_TYPES:
            issues.append(Issue("error", "bad-work-type", f"unknown work_type {work.work_type!r}", where))
        if work.metadata_status not in METADATA_STATUSES:
            issues.append(Issue("error", "bad-metadata-status", f"unknown metadata_status {work.metadata_status!r}", where))
        if work.title_status not in ("present", "unknown"):
            issues.append(Issue("error", "bad-title-status", f"unknown title_status {work.title_status!r}", where))
        if work.title_status == "present" and not work.title.strip():
            issues.append(Issue("error", "empty-title", "title_status=present but title is empty", where))
        if work.metadata_status == "verified" and work.title_status != "present":
            issues.append(Issue("error", "unverifiable-metadata", "metadata_status=verified requires a present title", where))
        if work.metadata_status == "unverified":
            issues.append(
                Issue("warning", "unverified-work", "metadata not verified against a source catalogue", where)
            )

        rights = work.rights
        if rights.access not in ACCESS_STATES:
            issues.append(Issue("error", "bad-access", f"unknown access {rights.access!r}", where))
        # Unknown-licence defaults are link-only. Publishing full text or an
        # abstract without recorded evidence is a hard error, not a warning.
        if rights.publish_fulltext and not rights.license_evidence_url:
            issues.append(
                Issue("error", "publish-without-evidence", "publish_fulltext=true requires license_evidence_url", where)
            )
        if rights.publish_abstract and not rights.license_evidence_url:
            issues.append(
                Issue("error", "publish-without-evidence", "publish_abstract=true requires license_evidence_url", where)
            )
        if rights.publish_fulltext and not rights.local_storage_allowed:
            issues.append(
                Issue("error", "publish-without-storage", "publish_fulltext=true but local_storage_allowed=false", where)
            )

        if work.work_type == "collection" and not work.members:
            issues.append(Issue("error", "empty-collection", "collection work has no members", where))
        for member in work.members:
            if member not in {a for w in corpus.works for a in w.aliases}:
                issues.append(Issue("error", "dangling-member", f"member {member} is not a known alias", where))
        if work.container and work.container not in {a for w in corpus.works for a in w.aliases}:
            issues.append(Issue("error", "dangling-container", f"container {work.container} is not a known alias", where))

        for asset in work.assets:
            a_where = f"{where}/{asset.id}"
            if asset.id in seen_asset_ids:
                issues.append(Issue("error", "duplicate-asset-id", f"duplicate asset id {asset.id}", a_where))
            seen_asset_ids.add(asset.id)
            if asset.role not in ASSET_ROLES:
                issues.append(Issue("error", "bad-role", f"unknown role {asset.role!r}", a_where))
            if asset.intent not in ACQUISITION_INTENTS:
                issues.append(Issue("error", "bad-intent", f"unknown intent {asset.intent!r}", a_where))
            if asset.intent != "ignore" and not asset.url:
                issues.append(Issue("error", "missing-url", f"intent={asset.intent} requires a url", a_where))
            if asset.url:
                if asset.url in seen_urls:
                    issues.append(
                        Issue("warning", "duplicate-url", f"url also used by {seen_urls[asset.url]}", a_where)
                    )
                seen_urls[asset.url] = a_where
                if not asset.url.startswith(("https://", "http://")):
                    issues.append(Issue("error", "bad-url-scheme", f"unsupported scheme in {asset.url}", a_where))
            if asset.intent == "required" and asset.role not in ("fulltext", "metadata", "mirror"):
                issues.append(
                    Issue("error", "required-non-content", f"intent=required is not meaningful for role {asset.role}", a_where)
                )

    expected = corpus.expected_aliases
    missing = [a for a in expected if a not in seen_aliases]
    if missing:
        issues.append(
            Issue("error", "missing-seed-alias", f"seed aliases absent from corpus: {', '.join(missing)}", "corpus")
        )
    return issues


def _validate_dependencies(corpus: Corpus, deps: Dependencies) -> list[Issue]:
    issues: list[Issue] = []
    alias_index = corpus.by_alias()
    work_ids = corpus.by_id()
    node_ids = deps.node_ids()
    seen: set[str] = set()

    for node in deps.nodes:
        if node.id in seen:
            issues.append(Issue("error", "duplicate-node", f"duplicate node {node.id}", node.id))
        seen.add(node.id)
        if node.kind not in NODE_KINDS:
            issues.append(Issue("error", "bad-node-kind", f"unknown kind {node.kind!r}", node.id))
        if node.kind in ("work", "collection"):
            if node.ref is None:
                issues.append(Issue("error", "node-missing-ref", f"{node.kind} node needs a ref", node.id))
            elif node.ref not in work_ids and node.ref not in alias_index:
                issues.append(Issue("error", "dangling-ref", f"ref {node.ref} matches no work", node.id))
        if node.kind == "choice":
            if len(node.options) < 2:
                issues.append(Issue("error", "degenerate-choice", "choice node needs at least two options", node.id))
            for option in node.options:
                if option not in node_ids:
                    issues.append(Issue("error", "dangling-choice-option", f"option {option} is not a node", node.id))

    for edge in deps.edges:
        where = f"{edge.source}->{edge.target}"
        if edge.type not in EDGE_TYPES:
            issues.append(Issue("error", "bad-edge-type", f"unknown edge type {edge.type!r}", where))
        if edge.source not in node_ids:
            issues.append(Issue("error", "dangling-edge-endpoint", f"unknown source {edge.source}", where))
        if edge.target not in node_ids:
            issues.append(Issue("error", "dangling-edge-endpoint", f"unknown target {edge.target}", where))
        if edge.source == edge.target:
            issues.append(Issue("error", "self-edge", "edge points at its own source", where))

    edge_keys = [e.key for e in deps.edges]
    duplicates = {k for k in edge_keys if edge_keys.count(k) > 1}
    for key in sorted(duplicates):
        issues.append(Issue("error", "duplicate-edge", f"edge {key} declared more than once", f"{key[0]}->{key[1]}"))

    cycle = find_cycle(deps)
    if cycle:
        issues.append(Issue("error", "dependency-cycle", "cycle: " + " -> ".join(cycle), "dependencies"))

    # Every work-kind alias in the corpus should appear in the DAG, or it is
    # unreachable in the navigator and effectively invisible.
    referenced = {n.ref for n in deps.nodes if n.ref}
    for work in corpus.works:
        if work.primary_alias not in referenced and work.id not in referenced:
            issues.append(
                Issue("warning", "work-not-in-dag", "work has no dependency node; it will be unreachable in navigation", work.primary_alias)
            )
    return issues


def _validate_choices(deps: Dependencies, profile: dict[str, str | None]) -> list[Issue]:
    issues: list[Issue] = []
    choices = {n.id: n for n in deps.nodes if n.kind == "choice"}
    for key, selected in profile.items():
        if key not in choices:
            issues.append(Issue("error", "unknown-choice", f"reading profile selects unknown choice {key}", key))
            continue
        if selected is not None and selected not in choices[key].options:
            issues.append(
                Issue("error", "bad-choice-selection", f"{selected} is not an option of {key}", key)
            )
    for key, node in choices.items():
        if key not in profile:
            issues.append(
                Issue("warning", "choice-not-in-profile", "choice has no entry in the reading profile", key)
            )
        elif profile.get(key) is None:
            issues.append(Issue("warning", "choice-unselected", f"{node.label} is unresolved", key))
    return issues


def find_cycle(deps: Dependencies) -> list[str] | None:
    """Return one cycle over ordering edges, or None. Backup/validates may cycle."""
    adjacency: dict[str, list[str]] = {n.id: [] for n in deps.nodes}
    for edge in deps.ordering_edges():
        if edge.source in adjacency and edge.target in adjacency:
            adjacency[edge.source].append(edge.target)
    for key in adjacency:
        adjacency[key].sort()

    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adjacency}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        color[node] = GREY
        stack.append(node)
        for nxt in adjacency[node]:
            if color[nxt] == GREY:
                return stack[stack.index(nxt):] + [nxt]
            if color[nxt] == WHITE:
                found = visit(nxt)
                if found:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    for node in sorted(adjacency):
        if color[node] == WHITE:
            found = visit(node)
            if found:
                return found
    return None


def errors(issues: Iterable[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]


def warnings(issues: Iterable[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "warning"]
