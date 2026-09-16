"""Extraction: honest field states, provenance, and the labelled-fixture gate.

The heading gate is measured against fixtures authored in this repository, so
it is a self-consistency check that catches regressions — not external
validation of real-world accuracy.
"""

import json
import unittest
from pathlib import Path

from bibgraph import extract, extract_html, extract_pdf, model, util
from bibgraph.store import Store

from .support import DEMO, WorkspaceCase

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "extraction"
NAMES = ("born-digital", "two-column", "book", "scanned", "non-english")


def load_fixture(name):
    text = (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")
    labels = json.loads((FIXTURES / f"{name}.labels.json").read_text(encoding="utf-8"))
    return text, labels


class TestNormalisation(unittest.TestCase):
    def test_line_endings_and_soft_hyphens_are_normalised(self):
        out = extract.normalize_conservative("a\r\nb­c  \nd")
        self.assertEqual(out, "a\nbc\nd")

    def test_dehyphenation_records_every_join(self):
        text = "trans-\nfer matrix and coun-\nting"
        joined, joins = extract.dehyphenate_with_map(text)
        self.assertEqual(joined, "transfer matrix and counting")
        self.assertEqual(len(joins), 2)
        for join in joins:
            # Each join can be traced back to the untouched layer.
            self.assertEqual(text[join["original_start"]:join["original_end"]],
                             join["removed"])

    def test_the_unmodified_layer_is_never_overwritten(self):
        text = "trans-\nfer"
        joined, _ = extract.dehyphenate_with_map(text)
        self.assertNotEqual(joined, text)
        self.assertIn("-\n", text)


class TestHeadingDetection(unittest.TestCase):
    def measure(self, name):
        text, labels = load_fixture(name)
        found = [util.normalize_for_match(h.title)
                 for h in extract.headings_from_text(text)]
        expected = [util.normalize_for_match(h) for h in labels["headings"]]
        true_positives = sum(1 for h in expected if h in found)
        precision = true_positives / len(found) if found else (1.0 if not expected else 0.0)
        recall = true_positives / len(expected) if expected else 1.0
        return precision, recall, found, expected

    def test_born_digital_meets_the_ninety_percent_gate(self):
        precision, recall, found, expected = self.measure("born-digital")
        self.assertGreaterEqual(precision, 0.90, f"found={found}")
        self.assertGreaterEqual(recall, 0.90, f"missing={set(expected) - set(found)}")

    def test_non_english_headings_are_found_through_the_vocabulary(self):
        precision, recall, found, expected = self.measure("non-english")
        self.assertGreaterEqual(recall, 0.90, f"missing={set(expected) - set(found)}")

    def test_book_chapters_are_found(self):
        _p, recall, found, expected = self.measure("book")
        self.assertGreaterEqual(recall, 0.90, f"missing={set(expected) - set(found)}")

    def test_a_scanned_page_yields_no_heading(self):
        text, _ = load_fixture("scanned")
        self.assertEqual(extract.headings_from_text(text), [])

    def test_shape_heuristics_are_scored_lower_than_markup(self):
        self.assertLess(extract.CONFIDENCE["shape-heuristic"],
                        extract.CONFIDENCE["numbered-heading"])
        self.assertLess(extract.CONFIDENCE["numbered-heading"],
                        extract.CONFIDENCE["semantic-markup"])

    def test_combined_conclusion_heading_is_recognised(self):
        self.assertEqual(extract.vocabulary_role("Discussion and Conclusions"),
                         "conclusion")
        self.assertEqual(extract.vocabulary_role("4. Conclusions"), "conclusion")
        self.assertEqual(extract.vocabulary_role("Literatur"), "references")
        self.assertIsNone(extract.vocabulary_role("Transfer matrices"))


class TestHtmlAdapter(unittest.TestCase):
    def setUp(self):
        self.parsed = extract_html.parse_html(
            (DEMO / "www" / "r0.html").read_text(encoding="utf-8"))

    def test_scripts_styles_and_navigation_are_removed(self):
        for noise in ("var tracker", "font-family", "Home", "Copyright notice"):
            self.assertNotIn(noise, self.parsed.text, noise)

    def test_citation_metadata_beats_heuristics(self):
        meta = extract_html.citation_metadata(self.parsed)
        self.assertEqual(meta["title"], "A Survey of Finite Structure Enumeration")
        self.assertEqual(meta["authors"], ["Ada Rivera", "Bo Chen"])
        self.assertEqual(meta["year"], "2019")

    def test_every_block_carries_a_character_span(self):
        for block in self.parsed.blocks:
            self.assertEqual(self.parsed.text[block.start:block.end], block.text)

    def test_heading_levels_come_from_the_markup(self):
        headings = extract.headings_from_blocks(self.parsed.blocks)
        levels = {h.title: h.level for h in headings}
        self.assertEqual(levels["Preorders"], 3)
        self.assertEqual(levels["Background"], 2)

    def test_jats_is_parsed_when_the_document_really_is_jats(self):
        jats = """<article xmlns:x="http://x"><front><article-meta>
        <article-id pub-id-type="doi">10.1234/x</article-id>
        <title-group><article-title>A JATS Paper</article-title></title-group>
        <abstract><p>An abstract.</p></abstract></article-meta></front>
        <body><sec><title>Introduction</title><p>Body text.</p></sec></body>
        <back><ref-list><ref>Smith, J. A Paper, 1999.</ref></ref-list></back></article>"""
        parsed = extract_html.parse_jats(jats)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.meta["citation_doi"], ["10.1234/x"])
        self.assertIn("An abstract.", parsed.text)

    def test_non_jats_xml_is_declined_rather_than_misparsed(self):
        self.assertIsNone(extract_html.parse_jats("<rss><channel/></rss>"))

    def test_malformed_markup_does_not_raise(self):
        parsed = extract_html.parse_html("<p>unclosed <b>bold <div>x</p>")
        self.assertIn("unclosed", parsed.text)


class TestPdfAdapter(unittest.TestCase):
    def test_absence_of_pdftotext_is_reported_not_worked_around(self):
        if extract_pdf.available():
            self.skipTest("pdftotext is installed in this environment")
        with self.assertRaises(extract_pdf.PdfUnsupported):
            extract_pdf.extract(DEMO / "www" / "paper.pdf")

    def test_the_reason_names_the_dependency_and_the_alternative(self):
        reason = extract_pdf.unavailable_reason()
        self.assertIn("pdftotext", reason)
        self.assertIn("sidecar", reason)

    def test_no_home_grown_pdf_parsing_exists(self):
        source = Path(extract_pdf.__file__).read_text(encoding="utf-8")
        for forbidden in ("zlib.decompress", "FlateDecode", "/Contents", "xref"):
            self.assertNotIn(forbidden, source.split('"""', 2)[2],
                             f"{forbidden} suggests a home-grown parser")

    def test_scanned_threshold_is_per_page(self):
        self.assertGreater(extract_pdf.SCANNED_CHARS_PER_PAGE, 0)


class TestReferenceSegmentation(unittest.TestCase):
    def test_bracketed_entries_split_on_the_marker_not_the_line(self):
        text, labels = load_fixture("born-digital")
        section = text.split("References", 1)[1]
        entries = extract.segment_references(section, [])
        self.assertEqual(len(entries), labels["expect_reference_count"])
        self.assertIn("Kleitman", entries[1]["raw"])
        # A wrapped continuation line belongs to the entry above it.
        self.assertIn("Proc. Amer. Math. Soc.", entries[1]["raw"])

    def test_hanging_indent_entries_are_split(self):
        text, labels = load_fixture("book")
        section = text.split("Bibliography", 1)[1]
        entries = extract.segment_references(section, [])
        self.assertEqual(len(entries), labels["expect_reference_count"])

    def test_the_raw_string_is_always_retained(self):
        entries = extract.segment_references("[1] A. Author. A Title, 1999.", [])
        self.assertEqual(entries[0]["raw"], "[1] A. Author. A Title, 1999.")

    def test_html_list_items_are_used_when_present(self):
        parsed = extract_html.parse_html(
            (DEMO / "www" / "r0.html").read_text(encoding="utf-8"))
        entries = extract.segment_references("", parsed.blocks)
        self.assertEqual(len(entries), 4)
        self.assertTrue(all(e["method"] == "list-item" for e in entries))

    def test_an_empty_section_yields_no_entry(self):
        self.assertEqual(extract.segment_references("   \n  ", []), [])


class TestFieldStates(WorkspaceCase):
    """Every fixture must produce the states a human labelled it with."""

    def extract_fixture(self, name):
        text, labels = load_fixture(name)
        work = model.Work(
            id=f"local:{name}", aliases=[name.upper()], title="",
            title_status="unknown", work_type=labels["work_type"],
            metadata_status="unverified", rights=model.Rights(), assets=[])
        store = Store(self.ws.state_db)
        self.addCleanup(store.close)
        source = self.root / f"{name}.txt"
        source.write_text(text, encoding="utf-8")
        store.record_artifact({
            "asset_id": f"{name}-a", "work_id": work.id, "alias": work.primary_alias,
            "role": "fulltext", "intent": "required", "requested_url": "user_supplied",
            "status": "downloaded", "media_type": "text/plain",
            "sha256": util.sha256_file(source), "path": str(source),
            "bytes": len(text), "attempts": 0,
        })
        artifacts = {row["asset_id"]: row for row in store.artifacts()}
        return extract.extract_work(self.ws, work, artifacts), labels

    def test_every_fixture_produces_its_labelled_states(self):
        for name in NAMES:
            with self.subTest(fixture=name):
                document, labels = self.extract_fixture(name)
                for field_name, expected in labels["expect_fields"].items():
                    self.assertEqual(document["fields"][field_name]["status"], expected,
                                     f"{name}.{field_name}")

    def test_no_field_is_ever_a_bare_empty_value(self):
        for name in NAMES:
            with self.subTest(fixture=name):
                document, _ = self.extract_fixture(name)
                for field_name, value in document["fields"].items():
                    self.assertIn(value["status"], model.FIELD_STATES, field_name)
                    if value["status"] != "present":
                        self.assertTrue(value["reason"],
                                        f"{name}.{field_name} is absent with no reason")
                    else:
                        self.assertTrue(value["text"], f"{name}.{field_name}")

    def test_every_present_passage_maps_back_to_source_evidence(self):
        for name in NAMES:
            with self.subTest(fixture=name):
                document, _ = self.extract_fixture(name)
                for field_name, value in document["fields"].items():
                    if value["status"] != "present":
                        continue
                    self.assertIsNotNone(value["source"], field_name)
                    self.assertEqual(len(value["source"]["asset_sha256"]), 64)
                    self.assertIsNotNone(value["method"])
                    self.assertGreater(value["confidence"], 0.0)

    def test_a_book_reports_not_applicable_rather_than_missing(self):
        document, _ = self.extract_fixture("book")
        conclusion = document["fields"]["conclusion"]
        self.assertEqual(conclusion["status"], "not_applicable")
        self.assertIn("book", conclusion["reason"])

    def test_a_combined_conclusion_heading_is_flagged(self):
        document, _ = self.extract_fixture("born-digital")
        warnings = document["fields"]["conclusion"]["warnings"]
        self.assertTrue(any("combined heading" in w for w in warnings), warnings)

    def test_a_scanned_page_claims_nothing(self):
        document, _ = self.extract_fixture("scanned")
        self.assertNotEqual(document["overall_status"], extract.STATUS_EXTRACTED)
        present = [n for n, f in document["fields"].items() if f["status"] == "present"]
        self.assertEqual(present, [])

    def test_reference_counts_match_the_labels(self):
        for name in NAMES:
            with self.subTest(fixture=name):
                document, labels = self.extract_fixture(name)
                self.assertEqual(len(document["raw_references"]),
                                 labels["expect_reference_count"], name)


class TestProvenanceGuards(WorkspaceCase):
    def test_hash_drift_refuses_extraction(self):
        store = Store(self.ws.state_db)
        self.addCleanup(store.close)
        source = self.root / "x.txt"
        source.write_text("1. Introduction\n\nBody.\n", encoding="utf-8")
        work = model.Work(id="local:x", aliases=["X"], title="", title_status="unknown",
                          work_type="article", metadata_status="unverified",
                          rights=model.Rights(), assets=[])
        store.record_artifact({
            "asset_id": "x-a", "work_id": work.id, "alias": "X", "role": "fulltext",
            "intent": "required", "requested_url": "u", "status": "downloaded",
            "media_type": "text/plain", "sha256": "0" * 64, "path": str(source),
            "bytes": 10, "attempts": 0})
        document = extract.extract_work(
            self.ws, work, {r["asset_id"]: r for r in store.artifacts()})
        self.assertEqual(document["overall_status"], extract.STATUS_FAILED)
        self.assertIn("hash drift", " ".join(document["warnings"]))

    def test_nothing_acquired_means_manual_required_not_extracted(self):
        work = model.Work(id="local:y", aliases=["Y"], title="", title_status="unknown",
                          work_type="article", metadata_status="unverified",
                          rights=model.Rights(), assets=[])
        document = extract.extract_work(self.ws, work, {})
        self.assertEqual(document["overall_status"], extract.STATUS_MANUAL_REQUIRED)
        self.assertTrue(all(f["status"] == "manual_required"
                            for f in document["fields"].values()))

    def test_a_collection_is_not_applicable_rather_than_empty(self):
        work = model.Work(id="local:c", aliases=["C"], title="", title_status="unknown",
                          work_type="collection", metadata_status="unverified",
                          rights=model.Rights(), assets=[], members=["A"])
        document = extract.extract_work(self.ws, work, {})
        self.assertTrue(all(f["status"] == "not_applicable"
                            for f in document["fields"].values()))
