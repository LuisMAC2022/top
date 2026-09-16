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
