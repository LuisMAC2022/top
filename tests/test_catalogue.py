"""The one-purpose catalogue importer, including its refusal behaviour."""

import tempfile
import unittest
from pathlib import Path

from bibgraph import catalogue, util

GOOD = """
Some prose that must be ignored.

| ID | Title | Type | Access | URL | Role | Intent | Authors | Year | Observed | License | License Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R0 | [A Survey](https://example.org/landing) | article | open | [PDF](https://example.org/r0.pdf) | fulltext | required | Rivera, A.; Chen, B. | 2019 | 200 OK | CC BY 4.0 | [licence](https://example.org/licence) |
| R0 | A Survey | article | open | https://example.org/landing | landing | metadata_only | | 2019 | | | |
| B1 | A Book | book | purchase | https://example.org/book | landing | metadata_only | Fontaine, E. | 2015 | catalogue only | | |
"""

NO_TABLE = "# Heading\n\nNo table here at all.\n"

WRONG_COLUMNS = """
| Identifier | Name | Link |
| --- | --- | --- |
| R0 | A Survey | https://example.org |
"""

BAD_VALUE = """
| ID | Title | Type | Access | URL | Role | Intent |
| --- | --- | --- | --- | --- | --- | --- |
| R0 | A Survey | article | open | https://example.org/x.pdf | sideways | required |
"""


def write(text):
    handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return Path(handle.name)


class TestImport(unittest.TestCase):
    def setUp(self):
        self.result = catalogue.import_catalogue(write(GOOD), observed_on="2026-09-16")
        self.works = {w["aliases"][0]: w for w in self.result["works"]}

    def test_one_work_may_span_several_rows(self):
        # "one row equals one downloadable file" is explicitly not assumed.
        self.assertEqual(len(self.result["works"]), 2)
        self.assertEqual(len(self.works["R0"]["assets"]), 2)

    def test_roles_and_intents_are_preserved_per_asset(self):
        roles = {a["role"]: a["intent"] for a in self.works["R0"]["assets"]}
        self.assertEqual(roles, {"fulltext": "required", "landing": "metadata_only"})

    def test_markdown_links_yield_url_and_plain_title(self):
        self.assertEqual(self.works["R0"]["title"], "A Survey")
        urls = {a["url"] for a in self.works["R0"]["assets"]}
        self.assertEqual(urls, {"https://example.org/r0.pdf", "https://example.org/landing"})

    def test_media_type_is_guessed_from_the_url(self):
        fulltext = [a for a in self.works["R0"]["assets"] if a["role"] == "fulltext"][0]
        self.assertEqual(fulltext["expected_media_type"], "application/pdf")

    def test_authors_and_year_are_parsed(self):
        self.assertEqual(self.works["R0"]["authors"], ["Rivera, A.", "Chen, B."])
        self.assertEqual(self.works["R0"]["year"], 2019)

    def test_open_access_does_not_enable_publication(self):
        rights = self.works["R0"]["rights"]
        self.assertTrue(rights["local_storage_allowed"])
        self.assertFalse(rights["publish_fulltext"])
        self.assertFalse(rights["publish_abstract"])

    def test_purchase_access_forbids_local_storage(self):
        self.assertFalse(self.works["B1"]["rights"]["local_storage_allowed"])

    def test_access_states_are_recorded_as_dated_observations(self):
        observation = self.works["B1"]["observations"][0]
        self.assertEqual(observation["observed_on"], "2026-09-16")
        self.assertEqual(observation["status"], "purchase")

    def test_import_is_deterministic(self):
        # Same file, twice: byte-identical output, source filename included.
        path = write(GOOD)
        first = catalogue.import_catalogue(path, observed_on="2026-09-16")
        second = catalogue.import_catalogue(path, observed_on="2026-09-16")
        self.assertEqual(util.canonical_json(first), util.canonical_json(second))


class TestRefusals(unittest.TestCase):
    def test_missing_table_names_the_required_columns(self):
        with self.assertRaises(catalogue.CatalogueError) as caught:
            catalogue.import_catalogue(write(NO_TABLE))
        for column in catalogue.REQUIRED_COLUMNS:
            self.assertIn(column, str(caught.exception))

    def test_wrong_columns_are_refused_rather_than_half_imported(self):
        with self.assertRaises(catalogue.CatalogueError):
            catalogue.import_catalogue(write(WRONG_COLUMNS))

    def test_out_of_vocabulary_value_is_refused(self):
        with self.assertRaises(catalogue.CatalogueError) as caught:
            catalogue.import_catalogue(write(BAD_VALUE))
        self.assertIn("role", str(caught.exception))


class TestPathSafety(unittest.TestCase):
    def test_traversal_is_rejected(self):
        for bad in ("..", ".", "a/b", "a\\b", "", "\x00"):
            with self.assertRaises(ValueError):
                util.safe_path_segment(bad)

    def test_ordinary_aliases_survive(self):
        self.assertEqual(util.safe_path_segment("A5.1"), "A5.1")
        self.assertEqual(util.safe_path_segment("choice:proof-foundation"),
                         "choice-proof-foundation")
