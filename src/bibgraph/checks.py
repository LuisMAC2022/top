"""Environment diagnosis, manifest validation, and run reporting."""

from __future__ import annotations

import os
import platform
import shutil
import sqlite3
import ssl
import subprocess
import sys
from pathlib import Path

from . import model, util
from .util import Workspace

# Environment variables the pipeline reads. Values are never printed or written
# into reports; only presence is reported.
SECRET_ENV = ("OPENALEX_API_KEY",)
PUBLIC_ENV = ("BIBGRAPH_CONTACT_EMAIL", "BIBGRAPH_USER_AGENT", "CROSSREF_MAILTO")


def pdftotext_path() -> str | None:
    return shutil.which("pdftotext")


def pdftotext_version() -> str | None:
    exe = pdftotext_path()
    if not exe:
        return None
    try:
        completed = subprocess.run(
            [exe, "-v"], capture_output=True, text=True, timeout=10, shell=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (completed.stderr or completed.stdout or "").strip().splitlines()
    return output[0] if output else None


def doctor(ws: Workspace) -> dict:
    """Report capabilities without printing a single secret value."""
    writable = {}
    for name in ("config", "data", "reports", "private", "cache", "build"):
        target = ws.root / name
        try:
            target.mkdir(parents=True, exist_ok=True)
            probe = target / ".bibgraph-write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            writable[name] = True
        except OSError:
            writable[name] = False

    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("create table t (a text)")
        connection.execute("pragma journal_mode=wal")
        sqlite_ok = True
        connection.close()
    except sqlite3.Error:
        sqlite_ok = False

    exe = pdftotext_path()
    return {
        "generated_at": util.now_iso(),
        "python": {
            "version": platform.python_version(),
            "executable": sys.executable,
            "supported": sys.version_info >= (3, 10),
        },
        "ssl": {
            "available": ssl.HAS_TLSv1_3 or hasattr(ssl, "create_default_context"),
            "openssl": ssl.OPENSSL_VERSION,
            "default_verify_paths": bool(ssl.get_default_verify_paths().cafile
                                         or ssl.get_default_verify_paths().capath),
        },
        "sqlite": {"version": sqlite3.sqlite_version, "usable": sqlite_ok},
        "pdftotext": {
            "present": bool(exe),
            "path": exe,
            "version": pdftotext_version(),
            "effect": ("PDF extraction available"
                       if exe else
                       "PDF extraction reports 'unsupported'; PDFs enter the manual queue"),
        },
        "writable": writable,
        "environment": {
            **{name: bool(os.environ.get(name)) for name in PUBLIC_ENV},
            **{f"{name}_set": bool(os.environ.get(name)) for name in SECRET_ENV},
        },
        "config_present": {
            "corpus.json": ws.corpus_file.exists(),
            "dependencies.json": ws.dependencies_file.exists(),
            "reading-profile.json": ws.profile_file.exists(),
            "ranking.json": ws.ranking_file.exists(),
            "stopwords.txt": ws.stopwords_file.exists(),
        },
    }


def format_doctor(report: dict) -> str:
    lines = ["bibgraph doctor", ""]
    py = report["python"]
    lines.append(f"  python            {py['version']} ({'ok' if py['supported'] else 'TOO OLD, need >= 3.10'})")
    lines.append(f"  ssl               {report['ssl']['openssl']}")
    lines.append(f"  sqlite            {report['sqlite']['version']} ({'usable' if report['sqlite']['usable'] else 'UNUSABLE'})")
    pdf = report["pdftotext"]
    lines.append(f"  pdftotext         {'present at ' + pdf['path'] if pdf['present'] else 'ABSENT'}")
    lines.append(f"                    {pdf['effect']}")
    lines.append("  writable          " + ", ".join(
        f"{k}={'yes' if v else 'NO'}" for k, v in sorted(report["writable"].items())))
    lines.append("  environment       " + ", ".join(
        f"{k}={'set' if v else 'unset'}" for k, v in sorted(report["environment"].items())))
    lines.append("  config            " + ", ".join(
        f"{k}={'found' if v else 'MISSING'}" for k, v in sorted(report["config_present"].items())))
    lines.append("")
    lines.append("  (no secret value is read back or written to any report)")
    return "\n".join(lines)


def load_and_validate(ws: Workspace) -> tuple[model.Corpus, model.Dependencies, dict, list[model.Issue]]:
    corpus = model.load_corpus(ws.corpus_file)
    deps = model.load_dependencies(ws.dependencies_file)
    profile = model.load_reading_profile(ws.profile_file) if ws.profile_file.exists() else {}
    issues = model.validate(corpus, deps, profile)
    return corpus, deps, profile, issues


def summarize_corpus(corpus: model.Corpus, deps: model.Dependencies) -> dict:
    intents: dict[str, int] = {}
    roles: dict[str, int] = {}
    for work in corpus.works:
        for asset in work.assets:
            intents[asset.intent] = intents.get(asset.intent, 0) + 1
            roles[asset.role] = roles.get(asset.role, 0) + 1
    edge_types: dict[str, int] = {}
    for edge in deps.edges:
        edge_types[edge.type] = edge_types.get(edge.type, 0) + 1
    return {
        "works": len(corpus.works),
        "seed_aliases_present": sum(1 for a in corpus.expected_aliases if a in corpus.by_alias()),
        "seed_aliases_expected": len(corpus.expected_aliases),
        "verified_works": sum(1 for w in corpus.works if w.metadata_status == "verified"),
        "assets": sum(len(w.assets) for w in corpus.works),
        "asset_intents": dict(sorted(intents.items())),
        "asset_roles": dict(sorted(roles.items())),
        "nodes": len(deps.nodes),
        "edges": len(deps.edges),
        "edge_types": dict(sorted(edge_types.items())),
        "choices": sum(1 for n in deps.nodes if n.kind == "choice"),
    }


def write_report(ws: Workspace, name: str, payload: dict, markdown: str) -> tuple[Path, Path]:
    ws.reports.mkdir(parents=True, exist_ok=True)
    json_path = ws.reports / f"{name}.jsonl"
    md_path = ws.reports / f"{name}.md"
    util.write_jsonl_atomic(json_path, [payload])
    util.write_text_atomic(md_path, markdown)
    return json_path, md_path


def render_validation_markdown(summary: dict, issues: list[model.Issue]) -> str:
    errs = model.errors(issues)
    warns = model.warnings(issues)
    lines = [
        "# Manifest validation",
        "",
        f"Generated: {util.now_iso()}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    for key, value in summary.items():
        lines.append(f"| {key} | {value} |")
    lines += ["", f"**Errors:** {len(errs)}  **Warnings:** {len(warns)}", ""]
    for label, bucket in (("Errors", errs), ("Warnings", warns)):
        lines += [f"## {label}", ""]
        if not bucket:
            lines += ["None.", ""]
            continue
        lines += ["| Code | Location | Message |", "| --- | --- | --- |"]
        for issue in bucket:
            lines.append(f"| `{issue.code}` | `{issue.location}` | {issue.message} |")
        lines.append("")
    return "\n".join(lines)


def render_fetch_markdown(summary: dict, outcomes: list) -> str:
    """Human-readable acquisition ledger. Local absolute paths never appear."""
    lines = [
        "# Acquisition report",
        "",
        f"Generated: {util.now_iso()}",
        "",
        "## Outcome counts",
        "",
        "| Status | Count |",
        "| --- | --- |",
    ]
    for status, count in summary["counts"].items():
        lines.append(f"| `{status}` | {count} |")
    lines += ["", "## Per asset", "",
              "| Alias | Role | Intent | Status | HTTP | Bytes | SHA-256 | Reason |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for outcome in outcomes:
        digest = (outcome.sha256 or "")[:12]
        lines.append(
            f"| {outcome.alias} | {outcome.role} | {outcome.intent} | `{outcome.status}` | "
            f"{outcome.http_status or ''} | {outcome.bytes or ''} | `{digest}` | "
            f"{(outcome.reason or '').replace('|', '/')} |")
    for label, key in (("Required assets that failed", "required_failures"),
                       ("Integrity failures", "integrity_failures"),
                       ("Full text not downloaded", "fulltext_not_downloaded"),
                       ("Works with no verified full text", "works_without_fulltext")):
        lines += ["", f"## {label}", ""]
        items = summary[key]
        lines.append("None." if not items else "\n".join(f"- `{i}`" for i in items))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Built-site checks
# ---------------------------------------------------------------------------

import html.parser as _html_parser
import re as _re
import urllib.parse as _urlparse


class _LinkCollector(_html_parser.HTMLParser):
    """Collect hrefs/srcs. Parsed as data; nothing fetched, nothing executed."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.ids: set[str] = set()
        self.has_title = False
        self.inline_scripts = 0
        self._in_title = False
        self.title = ""

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes and attributes["id"]:
            self.ids.add(attributes["id"])
        for key in ("href", "src"):
            if attributes.get(key):
                self.links.append((tag, attributes[key]))
        if tag == "title":
            self._in_title = True
            self.has_title = True
        if tag == "script" and not attributes.get("src"):
            self.inline_scripts += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


SECRET_PATTERNS = (
    _re.compile(r"(?i)\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    _re.compile(r"(?i)\b(api[_-]?key|secret|token|password)\b\s*[=:]\s*\S+"),
    _re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
)


def check_site(root: Path, public: bool = False) -> dict:
    """Traverse the built site: broken internal links, escaping, and leaks."""
    root = Path(root)
    issues: list[model.Issue] = []
    pages = sorted(root.rglob("*.html"))
    if not pages:
        issues.append(model.Issue("error", "empty-site", "no HTML page was produced", str(root)))

    existing = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    anchors: dict[str, set[str]] = {}
    parsed: dict[str, _LinkCollector] = {}

    for page_path in pages:
        collector = _LinkCollector()
        text = page_path.read_text(encoding="utf-8")
        collector.feed(text)
        key = page_path.relative_to(root).as_posix()
        parsed[key] = collector
        anchors[key] = collector.ids
        if not collector.has_title or not collector.title.strip():
            issues.append(model.Issue("error", "missing-title", "page has no title", key))
        if collector.inline_scripts:
            issues.append(model.Issue(
                "error", "inline-script",
                f"{collector.inline_scripts} inline <script> block(s); extracted "
                "content must never be executed", key))

    external = 0
    for key, collector in parsed.items():
        page_dir = Path(key).parent
        for _tag, link in collector.links:
            split = _urlparse.urlsplit(link)
            if split.scheme in ("http", "https"):
                external += 1
                continue
            if split.scheme and split.scheme not in ("", "mailto"):
                issues.append(model.Issue("error", "bad-link-scheme",
                                          f"unsupported scheme in {link}", key))
                continue
            if link.startswith("/"):
                issues.append(model.Issue(
                    "error", "absolute-link",
                    f"{link} is root-relative and breaks under a repository subpath", key))
                continue
            if not split.path:
                if split.fragment and split.fragment not in anchors.get(key, set()):
                    issues.append(model.Issue("error", "broken-anchor",
                                              f"#{split.fragment} is not on this page", key))
                continue
            target = (page_dir / split.path).as_posix()
            target = _urlparse.urlsplit(_normalize_rel(target)).path
            candidates = [target, target.rstrip("/") + "/index.html",
                          (target + "index.html") if target.endswith("/") else target]
            resolved = next((c for c in candidates if c in existing), None)
            if resolved is None:
                issues.append(model.Issue("error", "broken-link",
                                          f"{link} resolves to {target}, which does not exist", key))
            elif split.fragment and split.fragment not in anchors.get(resolved, set()):
                issues.append(model.Issue("warning", "broken-anchor",
                                          f"{link}: #{split.fragment} not found in {resolved}", key))

    if public:
        issues += _check_public_safety(root)

    return {
        "root": str(root),
        "pages": len(pages),
        "files": len(existing),
        "external_links": external,
        "issues": [i.as_dict() for i in issues],
        "errors": len(model.errors(issues)),
        "warnings": len(model.warnings(issues)),
    }


def _normalize_rel(path: str) -> str:
    parts: list[str] = []
    for segment in path.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    return "/".join(parts) + ("/" if path.endswith("/") else "")


def _check_public_safety(root: Path) -> list[model.Issue]:
    """Allowlist enforcement: nothing private may appear in a public build."""
    issues = []
    forbidden_dirs = ("private", "cache", "raw", "manual-import")
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        key = path.relative_to(root).as_posix()
        if any(part in forbidden_dirs for part in Path(key).parts):
            issues.append(model.Issue("error", "private-path",
                                      "private directory present in a public build", key))
        if path.suffix.lower() in (".pdf", ".sqlite3", ".db", ".part"):
            issues.append(model.Issue("error", "forbidden-artifact",
                                      f"{path.suffix} file present in a public build", key))
        if path.suffix.lower() not in (".html", ".css", ".js", ".json", ".svg", ".txt"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _re.search(r"(?m)^\s*/(home|Users|root|var|tmp)/", text) or \
                _re.search(r"[\"'>(]/(home|Users)/[A-Za-z0-9._-]+/", text):
            issues.append(model.Issue("error", "absolute-local-path",
                                      "an absolute local filesystem path appears in output", key))
        for pattern in SECRET_PATTERNS:
            match = pattern.search(text)
            if match:
                issues.append(model.Issue(
                    "error", "secret-pattern",
                    f"a {pattern.pattern.split('|')[0][:24]}-shaped value appears in output", key))
                break
    return issues
