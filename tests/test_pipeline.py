"""End-to-end: manifest, acquisition, extraction, annotation and site build."""

import json

from bibgraph import util

from .httpdouble import TestServer
from .support import WorkspaceCase


class TestFullRun(WorkspaceCase):
    def setUp(self):
        super().setUp()
        self.server = TestServer()
        self.server.__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        raw = json.loads(self.ws.corpus_file.read_text(encoding="utf-8"))
        for work in raw["works"]:
            for asset in work["assets"]:
                asset["url"] = asset["url"].replace("https://fixtures.invalid",
                                                    self.server.base_url)
        util.write_json_atomic(self.ws.corpus_file, raw)

    def fetch(self):
        return self.run_cli("fetch", "--allow-http",
                            "--allow-private-host", "127.0.0.1", "--delay", "0")

    def test_the_documented_command_sequence_runs(self):
        self.assertEqual(self.run_cli("doctor"), util.EXIT_OK)
        self.assertEqual(self.run_cli("validate"), util.EXIT_OK)
        self.assertEqual(self.fetch(), util.EXIT_OK)
        self.assertEqual(self.run_cli("extract"), util.EXIT_OK)
        self.assertEqual(self.run_cli("build-site", "--local"), util.EXIT_OK)
        self.assertEqual(self.run_cli("check-site", str(self.root / "build" / "site")),
                         util.EXIT_OK)

    def test_extraction_reaches_the_work_page_with_its_evidence(self):
        self.fetch()
        self.run_cli("extract")
        self.run_cli("build-site", "--local")
        page = (self.root / "build/site/works/D-R0/index.html").read_text(encoding="utf-8")
        self.assertIn("citation-meta", page)
        self.assertIn("0.98", page)                      # confidence is shown
        self.assertIn("A Survey of Finite Structure", page)
        self.assertNotIn("Not extracted yet", page)

    def test_an_unextractable_pdf_says_so_on_its_page(self):
        self.fetch()
        self.run_cli("extract")
        self.run_cli("build-site", "--local")
        page = (self.root / "build/site/works/D-PDF/index.html").read_text(encoding="utf-8")
        self.assertIn("manual_required", page)
        self.assertIn("pdftotext", page)

    def test_extract_strict_exits_two_while_the_manual_queue_is_not_empty(self):
        self.fetch()
        self.assertEqual(self.run_cli("extract", "--strict"), util.EXIT_INCOMPLETE)

    def test_reports_are_written_for_every_stage(self):
        self.run_cli("validate")
        self.fetch()
        self.run_cli("extract")
        names = {p.stem for p in (self.root / "reports").glob("*.md")}
        self.assertTrue({"validate", "extract"} <= names, names)
        self.assertTrue(any(n.startswith("fetch") for n in names), names)

    def test_a_run_is_reproducible_from_the_same_snapshot(self):
        self.fetch()
        self.run_cli("extract")
        first = {p.name: json.loads(p.read_text(encoding="utf-8"))
                 for p in (self.root / "data/documents").glob("*.json")}
        self.run_cli("extract")
        second = {p.name: json.loads(p.read_text(encoding="utf-8"))
                  for p in (self.root / "data/documents").glob("*.json")}
        self.assertEqual(util.canonical_json(first), util.canonical_json(second))

    def test_the_private_text_layer_stays_out_of_the_build(self):
        self.fetch()
        self.run_cli("extract")
        self.run_cli("build-site", "--local")
        raw_layer = self.root / "private/text/D-R0/raw.txt"
        self.assertTrue(raw_layer.exists())
        build = self.root / "build/site"
        self.assertEqual(list(build.rglob("raw.txt")), [])


class TestAnnotation(WorkspaceCase):
    def test_a_review_record_is_imported_and_surfaces_on_the_page(self):
        record = self.root / "review.json"
        record.write_text(json.dumps({
            "pass_status": "pass_1",
            "five_cs": {"category": "measurement paper", "context": "",
                        "correctness": "", "contributions": "", "clarity": ""},
        }), encoding="utf-8")
        self.assertEqual(self.run_cli("annotate", "D-R0", str(record)), util.EXIT_OK)
        self.assertTrue((self.root / "annotations/D-R0.json").exists())
        self.run_cli("build-site", "--local")
        page = (self.root / "build/site/works/D-R0/index.html").read_text(encoding="utf-8")
        self.assertIn("measurement paper", page)
        self.assertIn("pass_1", page)

    def test_an_invalid_pass_status_is_refused(self):
        record = self.root / "bad.json"
        record.write_text('{"pass_status": "pass_9"}', encoding="utf-8")
        self.assertEqual(self.run_cli("annotate", "D-R0", str(record)),
                         util.EXIT_INVALID_MANIFEST)

    def test_annotating_an_unknown_alias_is_refused(self):
        record = self.root / "r.json"
        record.write_text('{"pass_status": "unread"}', encoding="utf-8")
        self.assertEqual(self.run_cli("annotate", "NOPE", str(record)),
                         util.EXIT_INVALID_MANIFEST)
