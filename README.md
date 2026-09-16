# bibgraph

A local, reproducible bibliography-graph pipeline: acquire what is permitted,
extract first-pass structure with provenance, resolve references conservatively,
derive citation and coupling graphs, and generate a static site — with a
separate, allowlisted build that is safe to publish.

**Standard library only.** No Python packages are required. One optional system
adapter, Poppler's `pdftotext`, improves PDF extraction; without it PDFs are
reported as `manual_required` rather than silently half-scraped.

Read [VERIFICATION.md](VERIFICATION.md) first: it records where the source
catalogue is missing and which parts of the plan could not be followed literally.

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

## Current state of `config/`

The access-verification catalogue was not supplied, so the manifest holds 24
structural placeholders (20 seed aliases plus A5's four sequence children) with
no metadata and no dependency edges. Supply the catalogue to populate it:

```bash
./bin/bibgraph import-catalogue phase-1-access-verification.md --observed-on 2026-09-16
```

## Layout

| Path | Role |
| --- | --- |
| `config/` | human-reviewed source of truth: corpus, DAG, reading profile, ranking |
| `src/bibgraph/` | the pipeline |
| `private/` | acquired bytes and extracted text — never committed, never published |
| `data/` | deterministic JSON/JSONL exports; `state.sqlite3` is local-only |
| `reports/` | per-run failure and completeness ledgers |
| `annotations/` | human Keshav pass-two and pass-three notes |
| `build/site/` | local static application |
| `publish/` | allowlisted public build |
| `tests/fixtures/demo/` | synthetic end-to-end corpus |

## Reading method

The pipeline performs the mechanical part of S. Keshav's *How to Read a Paper*
first pass — title, abstract, introduction, headings, conclusions, references —
and nothing more. The five Cs (category, context, correctness, contributions,
clarity) are human review fields. No graph metric is allowed to stand in for
having read the paper.
