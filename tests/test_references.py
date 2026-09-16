"""Reference parsing and identifier normalisation."""

import unittest

from bibgraph import references


class TestDoiNormalisation(unittest.TestCase):
    CASES = [
        ("10.1016/S0021-9800(71)80011-5", "10.1016/s0021-9800(71)80011-5"),
        ("DOI: 10.1016/S0021-9800(71)80011-5", "10.1016/s0021-9800(71)80011-5"),
        ("doi:10.1016/S0021-9800(71)80011-5", "10.1016/s0021-9800(71)80011-5"),
        ("https://doi.org/10.1016/S0021-9800(71)80011-5", "10.1016/s0021-9800(71)80011-5"),
        ("https://dx.doi.org/10.1234/abc", "10.1234/abc"),
        ("10.1234/abc.", "10.1234/abc"),
        ("10.1234/abc,", "10.1234/abc"),
        ("see 10.1234/abc for details", "10.1234/abc"),
    ]

    def test_case_prefixes_and_punctuation_all_collapse(self):
        for raw, expected in self.CASES:
            with self.subTest(raw=raw):
                self.assertEqual(references.normalize_doi(raw), expected)

    def test_malformed_input_returns_none(self):
        for raw in ("", None, "not a doi", "10.x/abc", "doi:", "11.1234/abc"):
            with self.subTest(raw=raw):
                self.assertIsNone(references.normalize_doi(raw))


class TestIsbnNormalisation(unittest.TestCase):
    def test_isbn10_is_converted_to_isbn13(self):
        self.assertEqual(references.normalize_isbn("0-8218-1025-1"), "9780821810255")

    def test_isbn13_round_trips(self):
        self.assertEqual(references.normalize_isbn("978-0-8218-1025-5"), "9780821810255")

    def test_separators_are_irrelevant(self):
        self.assertEqual(references.normalize_isbn("978 0 8218 1025 5"), "9780821810255")

    def test_a_bad_checksum_is_rejected_rather_than_accepted(self):
        for raw in ("1234567890", "978-0-8218-1025-4", "0-8218-1025-2"):
            with self.subTest(raw=raw):
                self.assertIsNone(references.normalize_isbn(raw))

    def test_malformed_input_returns_none(self):
        for raw in ("", None, "abc", "12345"):
            self.assertIsNone(references.normalize_isbn(raw))


class TestAuthorNormalisation(unittest.TestCase):
    def test_both_name_orders_give_the_same_key(self):
        self.assertEqual(references.normalize_author("Alexandroff, P."),
                         references.normalize_author("P. Alexandroff"))

    def test_diacritics_and_case_are_folded(self):
        self.assertEqual(references.normalize_author("M. Erné"),
                         references.normalize_author("Erne, M."))

    def test_surname_extraction(self):
        self.assertEqual(references.surname("D. Kleitman"), "Kleitman")
        self.assertEqual(references.surname("Kleitman, D."), "Kleitman")
        self.assertEqual(references.surname("van der Waerden, B. L."), "van der Waerden")


class TestParsing(unittest.TestCase):
    def parse(self, raw):
        return references.parse_reference(1, raw)

    def test_a_full_journal_reference_is_decomposed(self):
        parsed = self.parse(
            "[3] R. Stanley. On the number of open sets of finite topologies. "
            "J. Combin. Theory Ser. A, 10(1):74-79, 1971. "
            "doi:10.1016/S0021-9800(71)80011-5")
        self.assertEqual(parsed.doi, "10.1016/s0021-9800(71)80011-5")
        self.assertEqual(parsed.year, 1971)
        self.assertEqual(parsed.volume, "10")
        self.assertEqual(parsed.pages, "74-79")
        self.assertEqual(parsed.authors, ["R. Stanley"])
        self.assertEqual(parsed.title, "On the number of open sets of finite topologies")

    def test_multiple_authors_are_all_captured(self):
        parsed = self.parse(
            "D. Kleitman and B. Rothschild. The number of finite topologies. "
            "Proc. Amer. Math. Soc., 25:276-282, 1970.")
        self.assertEqual(parsed.authors, ["D. Kleitman", "B. Rothschild"])
        self.assertEqual(parsed.title, "The number of finite topologies")

    def test_an_isbn_is_not_mistaken_for_a_page_range(self):
        parsed = self.parse(
            'Birkhoff, G. "Lattice Theory". AMS, 1940. ISBN 978-0-8218-1025-5')
        self.assertEqual(parsed.isbn, "9780821810255")
        self.assertIsNone(parsed.pages)
        self.assertEqual(parsed.year, 1940)

    def test_quoted_titles_are_trusted(self):
        parsed = self.parse('A. Author. "An Exact Title Here". Venue, 2001.')
        self.assertEqual(parsed.title, "An Exact Title Here")

    def test_the_raw_string_is_never_rewritten(self):
        raw = "  [1]   R. Stanley.   A Title.  1971. "
        self.assertEqual(self.parse(raw).raw, raw)

    def test_an_unparseable_entry_warns_rather_than_inventing(self):
        parsed = self.parse("ibid.")
        self.assertIsNone(parsed.title)
        self.assertTrue(parsed.warnings)

    def test_diacritics_survive_in_the_title(self):
        parsed = self.parse("P. Alexandroff. Diskrete Räume. Mat. Sbornik, 1937.")
        self.assertEqual(parsed.title, "Diskrete Räume")
