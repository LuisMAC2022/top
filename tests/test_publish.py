"""Publication allowlist, secret scanning, and security bounds."""

import json
import unittest
from pathlib import Path

from bibgraph import analysis, checks, model, site, util

from .httpdouble import TestServer
from .support import WorkspaceCase


class PublishCase(WorkspaceCase):
    def run_pipeline(self):
        with TestServer() as server:
            raw = json.loads(self.ws.corpus_file.read_text(encoding="utf-8"))
            for work in raw["works"]:
                for asset in work["assets"]:
                    asset["url"] = asset["url"].replace("https://fixtures.invalid",
                                                        server.base_url)
            util.write_json_atomic(self.ws.corpus_file, raw)
            self.run_cli("fetch", "--allow-http", "--allow-private-host",
                         "127.0.0.1", "--delay", "0")
            self.run_cli("extract")
            self.run_cli("resolve")

    def grant(self, alias, **rights):
        raw = json.loads(self.ws.corpus_file.read_text(encoding="utf-8"))
        for work in raw["works"]:
            if work["aliases"][0] == alias:
                work["rights"].update(rights)
        util.write_json_atomic(self.ws.corpus_file, raw)

    def build_public(self):
        code = self.run_cli("build-site", "--public")
        self.assertEqual(code, util.EXIT_OK, self.stderr.getvalue())
        return self.root / "publish"


class TestAllowlist(PublishCase):
    def test_full_text_is_withheld_without_licence_evidence(self):
        self.run_pipeline()
        root = self.build_public()
        page = (root / "works/D-R0/index.html").read_text(encoding="utf-8")
        self.assertNotIn("Counting the topologies on a finite set", page)
        self.assertIn("not cleared for publication", page)

    def test_full_text_is_included_only_with_recorded_evidence(self):
        self.grant("D-R0", publish_fulltext=True, local_storage_allowed=True,
                   license="CC BY 4.0",
                   license_evidence_url="https://example.org/licence")
        self.run_pipeline()
        root = self.build_public()
        page = (root / "works/D-R0/index.html").read_text(encoding="utf-8")
        self.assertIn("Counting the topologies on a finite set", page)

    def test_a_grant_without_evidence_is_refused_at_validation(self):
        self.grant("D-R0", publish_fulltext=True)
        self.assertEqual(self.run_cli("validate"), util.EXIT_INVALID_MANIFEST)

    def test_metadata_and_links_survive_for_an_unknown_licence(self):
        self.run_pipeline()
        root = self.build_public()
        page = (root / "works/D-BOOK/index.html").read_text(encoding="utf-8")
        self.assertIn("Structures, A Textbook", page)      # citation
        self.assertIn("book-landing.html", page)           # outbound link

    def test_local_filesystem_paths_never_appear(self):
        self.run_pipeline()
        root = self.build_public()
        for page in root.rglob("*.html"):
            text = page.read_text(encoding="utf-8")
            self.assertNotIn("/private/", text, page.name)
            self.assertNotIn(str(self.root), text, page.name)
        self.assertIn("held privately",
                      (root / "works/D-R0/index.html").read_text(encoding="utf-8"))

    def test_no_raw_artifact_is_copied_into_the_public_build(self):
        self.run_pipeline()
        root = self.build_public()
        self.assertEqual(list(root.rglob("*.pdf")), [])
        self.assertEqual(list(root.rglob("*.sqlite3")), [])
        self.assertEqual(list(root.rglob("raw.txt")), [])

    def test_private_annotations_are_withheld_unless_marked(self):
        record = self.root / "n.json"
        record.write_text(json.dumps({
            "pass_status": "pass_2",
            "pass_two": {"evidence": "A PRIVATE NOTE"}}), encoding="utf-8")
        self.run_cli("annotate", "D-R0", str(record))
        self.run_pipeline()
        root = self.build_public()
        self.assertNotIn("A PRIVATE NOTE",
                         (root / "works/D-R0/index.html").read_text(encoding="utf-8"))

    def test_an_annotation_marked_publish_is_included(self):
        record = self.root / "n.json"
        record.write_text(json.dumps({
            "pass_status": "pass_2", "publish": True,
            "pass_two": {"evidence": "A CLEARED NOTE"}}), encoding="utf-8")
        self.run_cli("annotate", "D-R0", str(record))
        self.run_pipeline()
        root = self.build_public()
        self.assertIn("A CLEARED NOTE",
                      (root / "works/D-R0/index.html").read_text(encoding="utf-8"))

    def test_the_publication_report_lists_every_included_passage(self):
        self.grant("D-R0", publish_abstract=True,
                   license_evidence_url="https://example.org/licence")
        self.run_pipeline()
        self.build_public()
        report = (self.root / "reports/publication.md").read_text(encoding="utf-8")
        self.assertIn("https://example.org/licence", report)
        self.assertIn("| D-R0 | abstract |", report)
        self.assertIn("## Withheld", report)

    def test_a_field_that_was_never_extracted_is_not_reported_as_a_rights_decision(self):
        self.run_pipeline()
        self.build_public()
        payload = util.read_jsonl(self.root / "reports/publication.jsonl")[0]
        book = [r for r in payload["withheld"]
                if r["alias"] == "D-BOOK" and r["field"] == "title"]
        self.assertTrue(book)
        self.assertIn("nothing to publish", book[0]["reason"])


class TestClearanceRules(unittest.TestCase):
    def work(self, **rights):
        return model.Work(id="x", aliases=["X"], title="T", title_status="present",
                          work_type="article", metadata_status="verified",
                          rights=model.Rights(**rights), assets=[])

    def test_open_access_alone_does_not_clear_redistribution(self):
        allowed, reason = site.clearance_for(
            self.work(access="open", local_storage_allowed=True), "introduction")
        self.assertFalse(allowed)
        self.assertIn("publish_fulltext=false", reason)

    def test_a_flag_without_evidence_does_not_clear(self):
        allowed, reason = site.clearance_for(
            self.work(publish_abstract=True), "abstract")
        self.assertFalse(allowed)
        self.assertIn("no licence evidence", reason)

    def test_a_flag_with_evidence_clears(self):
        allowed, _ = site.clearance_for(
            self.work(publish_abstract=True,
                      license_evidence_url="https://e/x"), "abstract")
        self.assertTrue(allowed)

    def test_metadata_defaults_to_publishable(self):
        self.assertTrue(site.clearance_for(self.work(), "title")[0])

    def test_an_unknown_field_is_refused_by_default(self):
        allowed, _ = site.clearance_for(self.work(), "secret_notes")
        self.assertFalse(allowed)


class TestSecretScanning(PublishCase):
    def test_an_email_address_in_output_is_caught(self):
        root = self.root / "fake-publish"
        (root).mkdir()
        (root / "index.html").write_text(
            "<html><head><title>t</title></head><body>"
            "contact person@example.org</body></html>", encoding="utf-8")
        report = checks.check_site(root, public=True)
        codes = {i["code"] for i in report["issues"]}
        self.assertIn("secret-pattern", codes)

    def test_an_api_key_shaped_value_is_caught(self):
        root = self.root / "fake2"
        root.mkdir()
        (root / "index.html").write_text(
            "<html><head><title>t</title></head><body>"
            "api_key: abcdef123456</body></html>", encoding="utf-8")
        self.assertIn("secret-pattern",
                      {i["code"] for i in checks.check_site(root, public=True)["issues"]})

    def test_an_absolute_local_path_is_caught(self):
        root = self.root / "fake3"
        root.mkdir()
        (root / "index.html").write_text(
            '<html><head><title>t</title></head><body>'
            '<a href="x">/home/someone/private/raw.pdf</a></body></html>',
            encoding="utf-8")
        self.assertIn("absolute-local-path",
                      {i["code"] for i in checks.check_site(root, public=True)["issues"]})

    def test_a_pdf_in_a_public_build_is_caught(self):
        root = self.root / "fake4"
        root.mkdir()
        (root / "index.html").write_text(
            "<html><head><title>t</title></head><body>ok</body></html>", encoding="utf-8")
        (root / "paper.pdf").write_bytes(b"%PDF-1.4\n")
        self.assertIn("forbidden-artifact",
                      {i["code"] for i in checks.check_site(root, public=True)["issues"]})

    def test_a_clean_public_build_passes(self):
        self.run_pipeline()
        root = self.build_public()
        report = checks.check_site(root, public=True)
        self.assertEqual([i for i in report["issues"] if i["severity"] == "error"], [],
                         report["issues"])


class TestSubpathAndBudget(PublishCase):
    def test_the_public_build_works_under_a_repository_subpath(self):
        self.run_pipeline()
        root = self.build_public()
        nested = self.root / "gh-pages" / "repository"
        nested.parent.mkdir(parents=True, exist_ok=True)
        root.rename(nested)
        self.assertEqual(checks.check_site(nested, public=True)["errors"], 0)

    def test_the_build_has_no_external_runtime_dependency(self):
        self.run_pipeline()
        root = self.build_public()
        for page in root.rglob("*.html"):
            text = page.read_text(encoding="utf-8")
            for marker in ("cdn.", "googleapis", "unpkg", "jsdelivr", "//cdnjs"):
                self.assertNotIn(marker, text, f"{page.name}: {marker}")

    def test_the_size_budget_is_measured(self):
        self.run_pipeline()
        root = self.build_public()
        size = site.measure_size(root)
        self.assertGreater(size["files"], 0)
        self.assertLess(size["bytes"], site.DEFAULT_SIZE_BUDGET_BYTES)
        self.assertTrue(size["largest"])


class TestSecurityBounds(unittest.TestCase):
    def test_oversized_json_is_refused_before_parsing(self):
        import tempfile

        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        handle.write('{"a": 1}')
        handle.close()
        with self.assertRaises(ValueError):
            util.read_json(Path(handle.name), max_bytes=2)

    def test_the_derived_graph_is_bounded(self):
        self.assertGreater(analysis.MAX_NODES, 0)
        self.assertGreater(analysis.MAX_EDGES, analysis.MAX_NODES)

    def test_external_adapters_are_invoked_without_a_shell(self):
        from bibgraph import extract_pdf

        source = Path(extract_pdf.__file__).read_text(encoding="utf-8")
        self.assertIn("shell=False", source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("os.system", source)

    def test_no_module_uses_a_shell_or_eval(self):
        package = Path(util.__file__).parent
        for module in sorted(package.glob("*.py")):
            text = module.read_text(encoding="utf-8")
            for forbidden in ("shell=True", "os.system(", "eval(", "exec(",
                              "pickle.load"):
                self.assertNotIn(forbidden, text, f"{module.name}: {forbidden}")

    def test_the_documented_local_server_binds_loopback(self):
        makefile = (Path(util.__file__).parents[2] / "Makefile").read_text(encoding="utf-8")
        self.assertIn("--bind 127.0.0.1", makefile)
