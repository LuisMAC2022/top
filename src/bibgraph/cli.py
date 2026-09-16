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

    p_fetch = sub.add_parser("fetch", help="acquire explicitly requested assets")
    p_fetch.add_argument("--strict", action="store_true",
                         help="stop at the first failed required asset")
    p_fetch.add_argument("--keep-going", action="store_true",
                         help="collect every failure; the exit status is unchanged")
    p_fetch.add_argument("--alias", action="append", default=None,
                         help="restrict to these aliases (repeatable)")
    p_fetch.add_argument("--require-fulltext-all", action="store_true",
                         help="exit 2 unless every fulltext asset was downloaded")
    p_fetch.add_argument("--allow-http", action="store_true",
                         help="permit plain http (refused by default)")
    p_fetch.add_argument("--allow-private-host", action="append", default=[],
                         help="permit a non-public host, e.g. 127.0.0.1 (repeatable)")
    p_fetch.add_argument("--no-robots", action="store_true",
                         help="skip robots.txt guidance (records the decision)")
    p_fetch.add_argument("--delay", type=float, default=1.0,
                         help="seconds between requests (default 1.0)")

    p_extract = sub.add_parser("extract", help="extract first-pass structure")
    p_extract.add_argument("--strict", action="store_true",
                           help="exit 2 if any work lands in the manual queue")
    p_extract.add_argument("--alias", action="append", default=None,
                           help="restrict to these aliases (repeatable)")
    p_extract.add_argument("--pdf-timeout", type=float, default=120.0)

    p_resolve = sub.add_parser("resolve", help="resolve references and build graphs")
    p_resolve.add_argument("--strict", action="store_true",
                           help="exit 2 if any reference is wholly unresolved")
    p_resolve.add_argument("--online", action="store_true",
                           help="allow optional Crossref lookups (off by default)")
    p_resolve.add_argument("--no-discovery", action="store_true",
                           help="do not create metadata-only candidate nodes")

    p_analyze = sub.add_parser("analyze", help="rebuild graphs, clusters and rankings")

    p_promote = sub.add_parser("promote",
                               help="propose a bounded expansion wave for review")
    p_promote.add_argument("--max-new", type=int, default=20)
    p_promote.add_argument("--min-citations", type=int, default=2)
    p_promote.add_argument("--year-from", type=int, default=None)
    p_promote.add_argument("--year-to", type=int, default=None)

    p_annotate = sub.add_parser("annotate", help="import a Keshav review record")
    p_annotate.add_argument("alias")
    p_annotate.add_argument("file")

    p_site = sub.add_parser("build-site", help="generate the static site")
    group = p_site.add_mutually_exclusive_group()
    group.add_argument("--local", action="store_true", default=True,
                       help="local build: keeps private material (default)")
    group.add_argument("--public", action="store_true",
                       help="allowlisted build for publication")
    p_site.add_argument("--output", default=None, help="destination directory")
    p_site.add_argument("--allow-incomplete", action="store_true",
                        help="build despite missing data, with visible badges")

    p_check = sub.add_parser("check-site", help="link-check and inspect a built site")
    p_check.add_argument("path")
    p_check.add_argument("--public", action="store_true",
                         help="also enforce the publication allowlist")

    p_local = sub.add_parser("import", help="register a legally obtained local copy")
    p_local.add_argument("alias")
    p_local.add_argument("file")
    p_local.add_argument("--role", default="fulltext")

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


def _load_or_exit(ws: Workspace):
    """Nothing touches the network until the manifest validates."""
    corpus, deps, profile, issues = checks.load_and_validate(ws)
    errors = model.errors(issues)
    if errors:
        for issue in errors:
            _err(str(issue))
        _err("manifest is invalid; refusing to continue")
        raise _Abort(EXIT_INVALID_MANIFEST)
    return corpus, deps, profile


class _Abort(Exception):
    def __init__(self, code: int):
        super().__init__(code)
        self.code = code


def cmd_fetch(args, ws: Workspace) -> int:
    from . import fetch as fetch_mod
    from .store import open_store

    ws.ensure()
    try:
        corpus, _deps, _profile = _load_or_exit(ws)
    except (model.ValidationError, FileNotFoundError, json.JSONDecodeError) as exc:
        _err(f"manifest could not be loaded: {exc}")
        return EXIT_INVALID_MANIFEST
    except _Abort as abort:
        return abort.code

    config = fetch_mod.FetchConfig.from_env(
        allow_http=args.allow_http,
        allow_private_hosts=tuple(args.allow_private_host),
        respect_robots=not args.no_robots,
        delay_between_requests=args.delay,
    )
    if not config.contact:
        _warn("BIBGRAPH_CONTACT_EMAIL is unset; requests carry no contact address")

    run_id = util.now_utc().strftime("%Y%m%dT%H%M%SZ")
    events: list[dict] = []

    def on_event(outcome) -> None:
        events.append(outcome.as_event())
        if outcome.status == fetch_mod.STATUS_FAILED:
            _err(f"{outcome.alias} [{outcome.role}] {outcome.requested_url}: {outcome.reason}")

    with open_store(ws.state_db) as store:
        outcomes = fetch_mod.fetch_corpus(
            ws, corpus, store, config,
            aliases=args.alias,
            keep_going=not args.strict or args.keep_going,
            fetcher=None, run_id=run_id, on_event=on_event,
        )

    summary = fetch_mod.summarize(outcomes, corpus)
    payload = {
        **util.derived_header(
            {"corpus.json": util.content_hash(util.read_json(ws.corpus_file))}, "fetch"),
        "run_id": run_id,
        "summary": summary,
        "events": events,
    }
    checks.write_report(ws, f"fetch-{run_id}", payload,
                        checks.render_fetch_markdown(summary, outcomes))
    checks.write_report(ws, "fetch", payload,
                        checks.render_fetch_markdown(summary, outcomes))

    if args.json:
        print(util.canonical_json(payload), end="")
    else:
        print("  ".join(f"{k}={v}" for k, v in summary["counts"].items()) or "nothing requested")
        print(f"fetch: report written to {ws.reports / f'fetch-{run_id}.md'}")

    return fetch_mod.exit_code_for(
        outcomes, require_fulltext_all=args.require_fulltext_all, corpus=corpus)


def cmd_import(args, ws: Workspace) -> int:
    from . import fetch as fetch_mod
    from .store import open_store

    ws.ensure()
    try:
        corpus, _deps, _profile = _load_or_exit(ws)
    except _Abort as abort:
        return abort.code
    with open_store(ws.state_db) as store:
        try:
            outcome = fetch_mod.import_local(
                ws, corpus, store, args.alias, Path(args.file), role=args.role)
        except fetch_mod.FetchError as exc:
            _err(str(exc))
            return EXIT_INVALID_MANIFEST
    print(f"imported {args.alias} <- {args.file}")
    print(f"  sha256 {outcome.sha256}")
    print(f"  stored {outcome.path} (provenance: user_supplied, never published by default)")
    return EXIT_OK


def cmd_build_site(args, ws: Workspace) -> int:
    from . import site as site_mod

    ws.ensure()
    try:
        corpus, deps, profile = _load_or_exit(ws)
    except (model.ValidationError, FileNotFoundError, json.JSONDecodeError) as exc:
        _err(f"manifest could not be loaded: {exc}")
        return EXIT_INVALID_MANIFEST
    except _Abort as abort:
        return abort.code

    public = bool(args.public)
    destination = Path(args.output) if args.output else (ws.publish if public else ws.build_site)
    data = site_mod.load_site_data(ws, corpus, deps, profile, public=public)

    publication_report = None
    if public:
        data, publication_report = site_mod.apply_public_allowlist(data)

    incomplete = _incompleteness(corpus, data)
    if incomplete and not args.allow_incomplete:
        for reason in incomplete:
            _err(reason)
        _err("build is incomplete; pass --allow-incomplete to build anyway "
             "(the site will carry visible incomplete badges)")
        return EXIT_INCOMPLETE

    written = site_mod.build_site(ws, data, destination)
    print(f"build-site: {len(written)} file(s) -> {destination}"
          f"{' (public, allowlisted)' if public else ''}")

    if publication_report is not None:
        checks.write_report(ws, "publication", publication_report,
                            site_mod.render_publication_report(publication_report))
        size = site_mod.measure_size(destination)
        publication_report["size"] = size
        print(f"  {publication_report['counts']['included']} passage(s) cleared for "
              f"publication, {publication_report['counts']['withheld']} withheld; "
              f"see {ws.reports / 'publication.md'}")
        print(f"  size {size['bytes'] / 1024:.1f} KiB in {size['files']} file(s)")
        if size["bytes"] > site_mod.DEFAULT_SIZE_BUDGET_BYTES:
            _err(f"public build is {size['bytes']} bytes, over the "
                 f"{site_mod.DEFAULT_SIZE_BUDGET_BYTES} byte budget; publish "
                 "metadata and graphs rather than copied documents")
            return EXIT_INCOMPLETE

    for reason in incomplete:
        _warn(reason)
    return EXIT_OK


def _incompleteness(corpus, data) -> list[str]:
    reasons = []
    if not corpus.source.get("supplied", False):
        reasons.append("corpus source catalogue was never supplied; "
                       "all metadata is placeholder")
    if not data.deps.edges:
        reasons.append("dependency graph has no edges; navigation is not meaningful")
    return reasons


def cmd_check_site(args, ws: Workspace) -> int:
    root = Path(args.path)
    if not root.is_dir():
        _err(f"not a directory: {root}")
        return EXIT_INVALID_MANIFEST
    report = checks.check_site(root, public=args.public)
    checks.write_report(
        ws, "check-site",
        {**util.derived_header({}, "check-site"), "summary": {
            "pages": report["pages"], "errors": report["errors"],
            "warnings": report["warnings"]}, **report},
        _render_check_site(report))
    if args.json:
        print(util.canonical_json(report), end="")
    else:
        print(f"check-site: {report['pages']} page(s), {report['files']} file(s), "
              f"{report['external_links']} external link(s)")
        for issue in report["issues"]:
            (_err if issue["severity"] == "error" else _warn)(
                f"{issue['code']} [{issue['location']}]: {issue['message']}")
        print(f"check-site: {report['errors']} error(s), {report['warnings']} warning(s)")
    return EXIT_OK if report["errors"] == 0 else EXIT_INCOMPLETE


def _render_check_site(report: dict) -> str:
    lines = ["# Site check", "", f"Generated: {util.now_iso()}", "",
             f"- pages: {report['pages']}", f"- files: {report['files']}",
             f"- external links: {report['external_links']}",
             f"- errors: {report['errors']}", f"- warnings: {report['warnings']}",
             "", "## Issues", ""]
    if not report["issues"]:
        lines.append("None.")
    else:
        lines += ["| Severity | Code | Location | Message |", "| --- | --- | --- | --- |"]
        for issue in report["issues"]:
            lines.append(f"| {issue['severity']} | `{issue['code']}` | "
                         f"`{issue['location']}` | {issue['message']} |")
    return "\n".join(lines) + "\n"


def cmd_extract(args, ws: Workspace) -> int:
    from . import extract as extract_mod
    from .store import open_store

    ws.ensure()
    try:
        corpus, _deps, _profile = _load_or_exit(ws)
    except (model.ValidationError, FileNotFoundError, json.JSONDecodeError) as exc:
        _err(f"manifest could not be loaded: {exc}")
        return EXIT_INVALID_MANIFEST
    except _Abort as abort:
        return abort.code

    with open_store(ws.state_db) as store:
        documents = extract_mod.extract_corpus(
            ws, corpus, store, aliases=args.alias, pdf_timeout=args.pdf_timeout)

    summary = extract_mod.summarize(documents)
    for document in documents:
        if document["overall_status"] in (extract_mod.STATUS_FAILED,
                                          extract_mod.STATUS_UNSUPPORTED):
            _err(f"{document['alias']}: {document['overall_status']}: "
                 f"{'; '.join(document['warnings'])[:300]}")
    payload = {
        **util.derived_header(
            {"corpus.json": util.content_hash(util.read_json(ws.corpus_file))}, "extract"),
        "summary": summary,
        "documents": [{k: v for k, v in d.items() if k != "fields"} | {
            "fields": {n: {kk: vv for kk, vv in f.items() if kk != "text"}
                       for n, f in d["fields"].items()}} for d in documents],
    }
    checks.write_report(ws, "extract", payload, _render_extract(summary, documents))

    if args.json:
        print(util.canonical_json(payload), end="")
    else:
        print("  ".join(f"{k}={v}" for k, v in summary["counts"].items()) or "nothing to extract")
        print(f"extract: {summary['references_found']} raw reference(s); "
              f"report written to {ws.reports / 'extract.md'}")
        if summary["manual_queue"]:
            _warn("manual queue: " + ", ".join(summary["manual_queue"]))
    return extract_mod.exit_code_for(documents, strict=args.strict)


def _render_extract(summary: dict, documents: list) -> str:
    lines = ["# Extraction report", "", f"Generated: {util.now_iso()}", "",
             "## Overall", "", "| Status | Count |", "| --- | --- |"]
    for status, count in summary["counts"].items():
        lines.append(f"| `{status}` | {count} |")
    lines += ["", "## Field states", "", "| Field | States |", "| --- | --- |"]
    for name, states in summary["field_states"].items():
        lines.append(f"| {name} | " + ", ".join(f"`{k}`={v}" for k, v in states.items()) + " |")
    lines += ["", "## Per work", "",
              "| Alias | Type | Adapter | Status | Sections | References | Warnings |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for document in documents:
        lines.append(
            f"| {document['alias']} | {document['work_type']} | `{document['adapter']}` | "
            f"`{document['overall_status']}` | {len(document['sections'])} | "
            f"{len(document['raw_references'])} | "
            f"{'; '.join(document['warnings'])[:160].replace('|', '/')} |")
    lines += ["", "## Manual queue", ""]
    lines.append("None." if not summary["manual_queue"]
                 else "\n".join(f"- {a}" for a in summary["manual_queue"]))
    return "\n".join(lines) + "\n"


def cmd_annotate(args, ws: Workspace) -> int:
    from .store import open_store

    ws.ensure()
    try:
        corpus, _deps, _profile = _load_or_exit(ws)
    except _Abort as abort:
        return abort.code
    work = corpus.by_alias().get(args.alias)
    if work is None:
        _err(f"unknown alias {args.alias}")
        return EXIT_INVALID_MANIFEST
    try:
        payload = util.read_json(Path(args.file))
    except (OSError, json.JSONDecodeError) as exc:
        _err(f"annotation could not be read: {exc}")
        return EXIT_INVALID_MANIFEST
    if not isinstance(payload, dict):
        _err("annotation must be a JSON object")
        return EXIT_INVALID_MANIFEST

    pass_status = str(payload.get("pass_status", "unread"))
    if pass_status not in ("unread", "pass_1", "pass_2", "pass_3"):
        _err(f"pass_status {pass_status!r} is not one of unread, pass_1, pass_2, pass_3")
        return EXIT_INVALID_MANIFEST

    ws.annotations.mkdir(parents=True, exist_ok=True)
    util.write_json_atomic(
        ws.annotations / f"{util.safe_path_segment(args.alias)}.json", payload)
    with open_store(ws.state_db) as store:
        store.set_review(work.id, pass_status, payload, util.now_iso())
    print(f"annotate: {args.alias} recorded at {pass_status}")
    return EXIT_OK


def _load_documents(ws: Workspace) -> dict[str, dict]:
    documents: dict[str, dict] = {}
    if ws.documents.exists():
        for path in sorted(ws.documents.glob("*.json")):
            document = util.read_json(path)
            documents[document.get("work_id", path.stem)] = document
    return documents


def _run_analysis(ws: Workspace, corpus, resolutions, command: str) -> dict:
    from . import analysis as analysis_mod
    from . import survey as survey_mod
    from .store import open_store

    ranking = util.read_json(ws.ranking_file) if ws.ranking_file.exists() else {}
    analysis = analysis_mod.analyze(ws, corpus, resolutions, ranking)
    analysis["unresolved"] = [
        {"citing": r.citing_alias, "raw": r.raw, "reason": r.reason}
        for r in resolutions if r.status in ("ambiguous", "unresolved")]
    analysis_mod.export(ws, corpus, resolutions, analysis, {
        "corpus.json": util.content_hash(util.read_json(ws.corpus_file)),
        "ranking.json": util.content_hash(ranking),
    })

    reviews = {}
    if ws.state_db.exists():
        with open_store(ws.state_db) as store:
            reviews = store.reviews()
    stopwords = survey_mod.load_stopwords(ws.stopwords_file)
    survey = survey_mod.build_survey(corpus, analysis, reviews, ranking, stopwords)
    util.write_json_atomic(ws.data / "survey.json", survey)
    return analysis


def cmd_resolve(args, ws: Workspace) -> int:
    from . import fetch as fetch_mod
    from . import resolve as resolve_mod

    ws.ensure()
    try:
        corpus, _deps, _profile = _load_or_exit(ws)
    except (model.ValidationError, FileNotFoundError, json.JSONDecodeError) as exc:
        _err(f"manifest could not be loaded: {exc}")
        return EXIT_INVALID_MANIFEST
    except _Abort as abort:
        return abort.code

    documents = _load_documents(ws)
    if not documents:
        _warn("no extracted document found; run `extract` first")

    crossref = None
    if args.online:
        config = fetch_mod.FetchConfig.from_env()
        if not config.contact:
            _warn("BIBGRAPH_CONTACT_EMAIL is unset; Crossref requests will not be "
                  "identified, which is what its polite pool asks for")
        crossref = resolve_mod.CrossrefClient(
            fetch_mod.Fetcher(config), ws.cache, mailto=config.contact)

    resolutions = resolve_mod.resolve_corpus(
        ws, corpus, documents, crossref=crossref,
        allow_discovery=not args.no_discovery)
    analysis = _run_analysis(ws, corpus, resolutions, "resolve")
    summary = resolve_mod.summarize(resolutions)

    payload = {
        **util.derived_header(
            {"corpus.json": util.content_hash(util.read_json(ws.corpus_file))}, "resolve"),
        "summary": summary,
        "graph_counts": {
            "citation_edges": len(analysis["citation_edges"]),
            "coupling_edges": len(analysis["coupling"]),
            "clusters": len(analysis["clusters"]),
            "discovered_works": len(analysis["discovered"]),
        },
    }
    checks.write_report(ws, "resolve", payload, _render_resolve(summary, resolutions))

    if args.json:
        print(util.canonical_json(payload), end="")
    else:
        print("  ".join(f"{k}={v}" for k, v in summary["counts"].items())
              or "no reference to resolve")
        print(f"resolve: {summary['auto_accepted']}/{summary['references']} auto-accepted; "
              f"{len(analysis['citation_edges'])} citation edge(s), "
              f"{len(analysis['discovered'])} discovered work(s)")
        if summary["manual_queue"]:
            _warn(f"{len(summary['manual_queue'])} reference(s) need human review")
    return resolve_mod.exit_code_for(resolutions, strict=args.strict)


def _render_resolve(summary: dict, resolutions: list) -> str:
    lines = ["# Reference resolution", "", f"Generated: {util.now_iso()}", "",
             f"Auto-accepted {summary['auto_accepted']} of {summary['references']} "
             f"reference(s). A match is accepted only when it is both strong and "
             f"unique; everything else is queued for review rather than merged.",
             "", "| Status | Count |", "| --- | --- |"]
    for status, count in summary["counts"].items():
        lines.append(f"| `{status}` | {count} |")
    lines += ["", "## Needs review", "",
              "| Citing | Raw reference | Best method | Score | Reason |",
              "| --- | --- | --- | --- | --- |"]
    for resolution in resolutions:
        if resolution.status in ("resolved", "discovered"):
            continue
        lines.append(
            f"| {resolution.citing_alias} | {resolution.raw[:70].replace('|', '/')} | "
            f"`{resolution.method or '-'}` | {resolution.confidence:.2f} | "
            f"{(resolution.reason or '').replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def cmd_analyze(args, ws: Workspace) -> int:
    from . import resolve as resolve_mod

    ws.ensure()
    try:
        corpus, _deps, _profile = _load_or_exit(ws)
    except _Abort as abort:
        return abort.code
    references_path = ws.data / "references.jsonl"
    if not references_path.exists():
        _err("data/references.jsonl is missing; run `resolve` first")
        return EXIT_INCOMPLETE

    rows = [r for r in util.read_jsonl(references_path) if "_meta" not in r]
    resolutions = [_resolution_from_row(row) for row in rows]
    analysis = _run_analysis(ws, corpus, resolutions, "analyze")
    survey = util.read_json(ws.data / "survey.json")
    print(f"analyze: {len(analysis['citation_edges'])} citation edge(s), "
          f"{len(analysis['coupling'])} coupling edge(s), "
          f"{len(analysis['clusters'])} cluster(s), "
          f"{len(survey['author_rankings'])} author identity/identities")
    if survey.get("sensitivity"):
        moved = sum(1 for row in survey["sensitivity"] if row["order_changed"])
        print(f"  shortlist order changes under {moved} of "
              f"{len(survey['sensitivity'])} weight variations")
    return EXIT_OK


def _resolution_from_row(row: dict):
    from .resolve import Candidate, Resolution

    return Resolution(
        citing_work_id=row["citing_work_id"], citing_alias=row["citing_alias"],
        reference_index=row["reference_index"], raw=row["raw"], parsed=row["parsed"],
        status=row["status"], target_id=row["target_id"], method=row["method"],
        confidence=row["confidence"], reason=row.get("reason"),
        candidates=[Candidate(c["target_id"], c["source"], c["score"], c["evidence"])
                    for c in row.get("candidates", [])])


def cmd_promote(args, ws: Workspace) -> int:
    from . import analysis as analysis_mod
    from . import resolve as resolve_mod

    ws.ensure()
    try:
        corpus, _deps, _profile = _load_or_exit(ws)
    except _Abort as abort:
        return abort.code
    references_path = ws.data / "references.jsonl"
    if not references_path.exists():
        _err("data/references.jsonl is missing; run `resolve` first")
        return EXIT_INCOMPLETE

    rows = [r for r in util.read_jsonl(references_path) if "_meta" not in r]
    resolutions = [_resolution_from_row(row) for row in rows]
    ranking = util.read_json(ws.ranking_file) if ws.ranking_file.exists() else {}
    analysis = analysis_mod.analyze(ws, corpus, resolutions, ranking)
    candidates = analysis_mod.promotion_candidates(
        analysis, args.max_new, args.min_citations, args.year_from, args.year_to)

    lines = ["# Promotion queue (proposal only)", "",
             f"Generated: {util.now_iso()}", "",
             f"Limits: max {args.max_new} new work(s), at least {args.min_citations} "
             f"citing corpus work(s)"
             + (f", years {args.year_from or ''}-{args.year_to or ''}"
                if (args.year_from or args.year_to) else "") + ".", "",
             "Nothing here has been downloaded or added to the manifest. Move an "
             "entry into `config/corpus.json` by hand, with a role, an acquisition "
             "intent and rights, to promote it.", "",
             "| Cited by | Year | Title | DOI | Authors |", "| --- | --- | --- | --- | --- |"]
    for row in candidates:
        lines.append(
            f"| {row['citing_count']} | {row.get('year') or ''} | "
            f"{(row.get('title') or '').replace('|', '/')[:80]} | "
            f"{row.get('doi') or ''} | "
            f"{'; '.join(row.get('authors') or [])[:60].replace('|', '/')} |")
    checks.write_report(ws, "promotion-queue", {
        **util.derived_header({}, "promote"),
        "summary": {"candidates": len(candidates),
                    "discovered_total": len(analysis["discovered"])},
        "candidates": candidates,
    }, "\n".join(lines) + "\n")
    print(f"promote: {len(candidates)} candidate(s) of "
          f"{len(analysis['discovered'])} discovered; "
          f"proposal written to {ws.reports / 'promotion-queue.md'}")
    print("  nothing was downloaded and the manifest was not modified")
    return EXIT_OK


COMMANDS = {
    "doctor": cmd_doctor,
    "fetch": cmd_fetch,
    "extract": cmd_extract,
    "resolve": cmd_resolve,
    "analyze": cmd_analyze,
    "promote": cmd_promote,
    "annotate": cmd_annotate,
    "build-site": cmd_build_site,
    "check-site": cmd_check_site,
    "import": cmd_import,
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
