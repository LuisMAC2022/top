# Verification of the implementation plan

This records what was checked before implementation began, what was found to be
sound, and the points where the plan could not be followed literally. It is kept
in the repository so the deviations are reviewable rather than buried in history.

## 1. Supplied input — resolved 2026-09-17

The catalogue and relationship constraints were subsequently supplied. They
are preserved in `phase-1-access-verification.md`; `config/corpus.json` now
contains 24 works and 54 routes observed on 2026-09-16, while
`config/dependencies.json` contains 26 nodes and 18 reviewed, typed edges. A5
is a collection of four independently named OEIS sequence records, and the
choices `A7 | C2` and `A2 | A3` intentionally remain unresolved.

The corpus can be regenerated with:

```bash
./bin/bibgraph import-catalogue phase-1-access-verification.md --observed-on 2026-09-16
```

Dependency edges remain curated data rather than importer output, so regenerating
the corpus does not overwrite `config/dependencies.json`. A complete synthetic
corpus remains at `tests/fixtures/demo/` for deterministic, offline pipeline
tests; it exercises all six edge types, a choice node, a collection, a
purchase-only work, and a PDF.

## 2. Defects found in the plan, and how they were resolved

| # | Plan text | Problem | Resolution |
|---|---|---|---|
| 1 | §4 layout `src/bibgraph/`, §11 `python -m bibgraph …` | With a `src/` layout and no packaging step — which §1 forbids — `python -m bibgraph` does not resolve. | Package stays at `src/bibgraph/`. `bin/bibgraph` and the `Makefile` set `PYTHONPATH=src`. `tests/__init__.py` does the same for the test suite, so the §11 gate `python -m unittest` works unchanged from a clean checkout. |
| 2 | §6 "exit codes are `0`, `2`, `3`, `4`" | No precedence rule; a run can satisfy several conditions at once. | `util.resolve_exit_code` fixes the order `3 > 4 > 2 > 0`, most-diagnostic first. Tested. |
| 3 | §6 step 2, "Check and cache `robots.txt`" | `urllib.robotparser.RobotFileParser.read()` calls `urlopen` itself with **no timeout and no byte cap**, contradicting the plan's own bounded-fetch requirement in step 5. | robots.txt is fetched through the same bounded fetcher as everything else and handed to `RobotFileParser.parse()`. `read()` is never called. |
| 4 | §8 "forms export a JSON download" vs §7 "useful with JavaScript disabled" | A Blob download needs JavaScript. As written the two gates contradict. | Work pages render the Keshav record as a pre-filled, selectable `<textarea>` that works with JS off; a download button is added by progressive enhancement when JS is available. Either way the CLI imports the JSON. |
| 5 | §4 puts `data/state.sqlite3` beside versioned JSONL | A binary transactional database must not be committed; it would make every diff unreadable and every run dirty the tree. | `data/*.jsonl` and `data/documents/` are versioned; `data/state.sqlite3` and `cache/` are git-ignored. The JSONL exports remain the reproducible source of truth. |
| 6 | §8, §9 quantitative gates ("90% heading precision", "98% resolution precision") | Measured against fixtures authored in this repository, so they are self-consistency checks, not external validation. | Implemented and enforced, and labelled as such in the reports. They catch regressions; they do not prove real-world accuracy. |

## 3. Claims checked and found sound

- Standard library covers HTTP, TLS, SQLite, HTML/XML parsing, templating,
  graph algorithms, TF–IDF and the test suite. Verified on Python 3.11.
- The Salton-cosine coupling formula is stated correctly.
- `pdftotext` is genuinely absent in this environment, so the `unsupported` /
  `manual_required` path is the live default rather than an untested branch.
- The refusal to write a Python PDF parser is correct and is honoured.

## 4. Defects found *during* implementation

These were not visible from reading the plan. Each was caught by a test or by
running the pipeline, and each is fixed with a regression test.

| Where | Defect | Why it mattered |
|---|---|---|
| `fetch` | A single 512-byte "stub response" floor rejected legitimately short pages. | The seed corpus contains OEIS sequence pages, which are exactly that shape. The floor is now work-type aware with a per-asset override. |
| `fetch` | `--require-fulltext-all` checked fulltext *assets*. | A purchase-only work has no fulltext asset at all, so the flag passed precisely the gated works it exists to surface. It now counts works. |
| `extract_html` | JATS abstracts and reference lists were silently dropped. | `ElementTree.iter()` takes an exact tag; `"{*}p"` is find/findall syntax. A JATS article extracted with no abstract and no references, and nothing said so. |
| `extract` | Artifact lookup was keyed on the declared asset list. | A manually imported copy made the work look unacquired. Now keyed on `work_id`. |
| `extract` | Hanging-indent bibliographies collapsed into one entry. | The branch that starts an entry required a previous entry of the same style, so the first never started one. Style is now decided once per section. |
| `references` | Splitting on `.` to find the author list truncated multi-author entries. | Initials are full of periods, so "D. Kleitman and B. Rothschild" lost its second author *and* the title started one name late. |
| `references` | An ISBN's digit groups were parsed as a page range. | Identifiers are now scrubbed before volume/page detection. |
| `references` | `normalize_author` read initials only from `X.` patterns. | "Cleo Duarte" and "C. Duarte" got different identity keys — a false split in the author index, not the conservative non-merge it resembles. |
| `analysis` | The same paper cited with a DOI in one bibliography and without one in another became two nodes. | This is the false-split failure the plan predicts, and it inflated every count derived from those nodes. Discovered records now merge on exact title, year and first-author surname together. |
| `survey` | `leave_one_out` removed a work's edges but not the work. | It reappeared at the bottom of the rebuilt ranking with every dimension zeroed, reading as a result rather than as the hole it is. |
| `site` | The stylesheet was not copied for a project root outside the repository. | The site rendered unstyled with broken asset links. Now a hard failure, caught by the link checker. |
| `survey` | "Independent seed groups" was hardcoded to an alias prefix. | The measure only means something relative to how the seed bibliography was organised, so the pattern is now declared in `config/ranking.json`. |

## 5. Definition of done, audited

Against the plan's section 3:

| Requirement | State |
|---|---|
| Every seed record and asset in a validated manifest | **Met.** 24 works, 20/20 seed aliases, A5 expanded, and 54 catalogued routes. |
| Downloads verified and hashed, or a specific recorded failure; nonzero exit | **Met.** Exercised against 403, 404, 429, timeout, truncation, wrong media type, oversized body, redirect loop and an HTML login served as a PDF. |
| DAG navigable with upstream, downstream, branch, Previous and Next | **Met.** The checked configuration has 26 nodes and 18 typed edges; behavior is also exercised against the offline demo corpus. |
| Every field has an explicit state; empty never means success | **Met**, across five hand-labelled fixtures. |
| Every passage carries provenance and confidence | **Met.** |
| Every citation edge keeps its raw string and resolution evidence | **Met.** |
| Rankings and survey reproducible from versioned data | **Met.** Byte-identical re-runs are tested. |
| Local build private by default; public build allowlisted | **Met.** |
| Clean checkout runs the test suite and rebuilds | **Met.** 271 tests from a fresh clone. |

Two quantitative gates — 90% heading precision and recall, 98% auto-accept
precision — are enforced against fixtures authored in this repository. They
catch regressions. They are not external validation of real-world accuracy, and
should not be quoted as if they were.
