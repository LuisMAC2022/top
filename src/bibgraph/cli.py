"""Command line entry point.

Every command returns one of the documented exit codes. `--keep-going` may let
a run collect several failures, but it never downgrades the final status.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import checks, model, util
from .util import (
    EXIT_INCOMPLETE,
    EXIT_INVALID_MANIFEST,
    EXIT_OK,
    Workspace,
)


def _err(message: str) -> None:
    """One concise line on stderr, coloured only when stderr is a terminal."""
    if sys.stderr.isatty():
        sys.stderr.write(f"\033[31merror\033[0m {message}\n")
    else:
        sys.stderr.write(f"error {message}\n")


def _warn(message: str) -> None:
    if sys.stderr.isatty():
        sys.stderr.write(f"\033[33mwarn\033[0m  {message}\n")
    else:
        sys.stderr.write(f"warn  {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bibgraph",
        description="Local bibliography graph pipeline (standard library only).",
    )
    parser.add_argument("--root", default=".", help="project root (default: .)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="report environment capabilities")

    p_validate = sub.add_parser("validate", help="validate the manifests")
    p_validate.add_argument("--strict", action="store_true",
                            help="treat warnings as failures")

    p_import = sub.add_parser("import-catalogue",
                              help="convert the access-verification Markdown into corpus.json")
    p_import.add_argument("path", help="catalogue Markdown file")
    p_import.add_argument("--observed-on", default=None,
                          help="date the access states were observed, e.g. 2026-09-16")
    p_import.add_argument("--output", default=None,
                          help="destination (default: config/corpus.json)")
    p_import.add_argument("--dry-run", action="store_true",
                          help="print the result instead of writing it")
    return parser


def cmd_doctor(args, ws: Workspace) -> int:
    report = checks.doctor(ws)
    if args.json:
        print(util.canonical_json(report), end="")
    else:
        print(checks.format_doctor(report))
    if not report["python"]["supported"]:
        _err("python >= 3.10 is required")
        return EXIT_INCOMPLETE
    if not report["sqlite"]["usable"]:
        _err("sqlite3 is not usable in this interpreter")
        return EXIT_INCOMPLETE
    if not all(report["writable"].values()):
        _err("some project directories are not writable")
        return EXIT_INCOMPLETE
    return EXIT_OK


def cmd_validate(args, ws: Workspace) -> int:
    try:
        corpus, deps, _profile, issues = checks.load_and_validate(ws)
    except (model.ValidationError, FileNotFoundError, json.JSONDecodeError) as exc:
        _err(f"manifest could not be loaded: {exc}")
        return EXIT_INVALID_MANIFEST

    summary = checks.summarize_corpus(corpus, deps)
    errors = model.errors(issues)
    warnings = model.warnings(issues)
    payload = {
        **util.derived_header(
            {
                "corpus.json": util.content_hash(util.read_json(ws.corpus_file)),
                "dependencies.json": util.content_hash(util.read_json(ws.dependencies_file)),
            },
            "validate",
        ),
        "summary": summary,
        "issues": [i.as_dict() for i in issues],
        "errors": len(errors),
        "warnings": len(warnings),
    }
    checks.write_report(ws, "validate", payload, checks.render_validation_markdown(summary, issues))

    if args.json:
        print(util.canonical_json(payload), end="")
    else:
        print(f"works {summary['works']}  nodes {summary['nodes']}  edges {summary['edges']}  "
              f"seeds {summary['seed_aliases_present']}/{summary['seed_aliases_expected']}")
        for issue in warnings:
            _warn(str(issue))
        for issue in errors:
            _err(str(issue))
        print(f"validate: {len(errors)} error(s), {len(warnings)} warning(s); "
              f"report written to {ws.reports / 'validate.md'}")

    if errors:
        return EXIT_INVALID_MANIFEST
    if warnings and args.strict:
        _err("--strict: warnings are treated as failures")
        return EXIT_INVALID_MANIFEST
    return EXIT_OK


def cmd_import_catalogue(args, ws: Workspace) -> int:
    from . import catalogue

    source = Path(args.path)
    if not source.exists():
        _err(f"catalogue not found: {source}")
        return EXIT_INVALID_MANIFEST
    try:
        result = catalogue.import_catalogue(source, observed_on=args.observed_on)
    except catalogue.CatalogueError as exc:
        _err(f"catalogue could not be imported: {exc}")
        return EXIT_INVALID_MANIFEST

    if args.dry_run:
        print(util.canonical_json(result), end="")
        return EXIT_OK

    destination = Path(args.output) if args.output else ws.corpus_file
    util.write_json_atomic(destination, result)
    aliases = [w["aliases"][0] for w in result["works"]]
    missing = [a for a in model.SEED_ALIASES if a not in aliases]
    print(f"imported {len(result['works'])} work(s), "
          f"{sum(len(w['assets']) for w in result['works'])} asset(s) -> {destination}")
    if missing:
        _warn("seed aliases not present in the catalogue: " + ", ".join(missing))
    return EXIT_OK


COMMANDS = {
    "doctor": cmd_doctor,
    "validate": cmd_validate,
    "import-catalogue": cmd_import_catalogue,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    ws = Workspace.from_root(args.root)
    handler = COMMANDS.get(args.command)
    if handler is None:  # pragma: no cover - argparse already rejects this
        parser.error(f"unknown command {args.command}")
    return handler(args, ws)
