# bibgraph

A local, reproducible bibliography-graph pipeline: acquire what is permitted,
extract first-pass structure with provenance, resolve references
conservatively, derive citation and coupling graphs, and generate a static
site — with a separate, allowlisted build that is safe to publish.

**Standard library only.** No Python packages are required. One optional system
adapter, Poppler's `pdftotext`, improves PDF extraction; without it PDFs are
reported as `manual_required` rather than silently half-scraped.

Read [VERIFICATION.md](VERIFICATION.md) first: it records where the source
catalogue is missing and which parts of the plan could not be followed
literally.

For step-by-step instructions in clear Spanish, including environment setup,
catalogue import, every CLI command, troubleshooting, backups, and safe
publication, see the [complete HTML user manual](MANUAL_USUARIO.html) (also available as [Markdown source](MANUAL_USUARIO.md)).

## Quick start

```bash
python3 -m unittest            # test suite, from a clean checkout
./bin/bibgraph doctor          # what this machine can and cannot do
./bin/bibgraph validate        # manifest gate; nothing runs until this passes
```

`bin/bibgraph` is a launcher that puts `src/` on `PYTHONPATH`. Equivalently:

```bash
PYTHONPATH=src python3 -m bibgraph <command>
```

## The pipeline

```bash
./bin/bibgraph doctor
./bin/bibgraph validate
./bin/bibgraph fetch --strict
./bin/bibgraph extract --strict
./bin/bibgraph resolve --strict
./bin/bibgraph analyze
./bin/bibgraph build-site --local
./bin/bibgraph check-site build/site
python3 -m http.server --bind 127.0.0.1 --directory build/site 8000
```

`make help` lists the same steps as shortcuts.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | complete |
| 2 | acquisition or extraction incomplete |
| 3 | invalid manifest |
| 4 | integrity or media-type mismatch |

When several apply at once the most diagnostic wins: `3 > 4 > 2 > 0`.
`--keep-going` collects more failures but never lowers the final status.
Continuing past missing data needs `--allow-incomplete`, and the site then
carries visible incomplete notices.

## Current state of `config/`

The checked access-verification catalogue is committed as
`phase-1-access-verification.md`. The manifest contains its 20 seed records,
the four individual OEIS sequences grouped by A5, all 54 recorded routes, and
the curated dependency relationships. Re-import it reproducibly with:

```bash
./bin/bibgraph import-catalogue phase-1-access-verification.md --observed-on 2026-09-16
```

The importer handles exactly one table shape and refuses anything else by
naming the columns it found and the columns it needs. Required columns:
`ID, Title, Type, Access, URL, Role, Intent`. Optional: `Authors, Year,
License, License Evidence, Observed, Notes, Container, Members`. One work may
span several rows, one row per asset.

Dependency edges are curated data and are not derivable from the table; the
reviewed relationships are stored separately in `config/dependencies.json`.

## Acquisition policy

- Only assets with an explicit acquisition intent are requested.
- `https` only unless `--allow-http` is passed; embedded credentials and
  private, loopback and link-local addresses are refused.
- robots.txt is honoured as crawl guidance, fetched under the same byte and
  time bounds as everything else.
- Bodies are validated on status, size, declared media type and magic bytes
  before being renamed into place, so a partial or mislabelled artifact never
  reaches a final path.
- 401, 403, 404 and login pages are recorded as gates. No login, challenge,
  cookie reuse or paywall bypass exists anywhere in this codebase.
- For a legally obtained copy: `bibgraph import <alias> <file>`, stored with
  `user_supplied` provenance and never published by default.

## Rights and publication

Defaults are link-only. `publish_fulltext` or `publish_abstract` without a
recorded `license_evidence_url` is a validation **error**, not a warning, and
open web access is never treated as redistribution permission.

`build-site --public` is an allowlist: it starts from nothing and copies in
only cleared metadata, cleared passages, derived graph data, outbound links and
annotations explicitly marked `"publish": true`. Every included passage is
listed in `reports/publication.md` with its licence evidence.
`check-site --public` then scans for private paths, raw artifacts, absolute
local paths and secret-shaped values, and measures the size budget.

## Layout

| Path | Role |
| --- | --- |
| `config/` | human-reviewed source of truth: corpus, DAG, reading profile, ranking |
| `src/bibgraph/` | the pipeline |
| `private/` | acquired bytes and extracted text — never committed, never published |
| `data/` | deterministic JSON/JSONL exports; `state.sqlite3` is local-only |
| `reports/` | per-run failure, completeness and publication ledgers |
| `annotations/` | human Keshav pass-two and pass-three notes |
| `build/site/` | local static application |
| `publish/` | allowlisted public build |
| `tests/fixtures/demo/` | synthetic end-to-end corpus |
| `tests/fixtures/extraction/` | hand-labelled extraction fixtures |
| `tests/fixtures/resolution/` | hand-labelled resolution cases |

## Reading method

The pipeline performs the mechanical part of S. Keshav's *How to Read a Paper*
first pass — title, abstract, introduction, headings, conclusions, references —
and nothing more. The five Cs (category, context, correctness, contributions,
clarity) are human review fields, exported from each work page as JSON and
imported with `bibgraph annotate`. No graph metric is allowed to stand in for
having read the paper, and no work may be described as supporting or
contradicting a claim on shared-citation evidence alone.

## What this deliberately does not do

General web crawling, recursive downloading, login automation, paywall
circumvention, CAPTCHA handling, cookie reuse, a Python PDF parser or OCR
engine, Google Scholar scraping, a universal "best paper" score, or publishing
a mirror of the acquired bibliography.
