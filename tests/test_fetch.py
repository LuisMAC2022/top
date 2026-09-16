"""Acquisition: URL policy, integrity, retry semantics and exit codes.

Everything is served by the local test double; no test touches a publisher.
"""

import json
import unittest
from pathlib import Path

from bibgraph import fetch, model, util
from bibgraph.store import Store

from .httpdouble import TestServer
from .support import WorkspaceCase

LOCAL_CONFIG = dict(
    allow_http=True,
    allow_private_hosts=("127.0.0.1", "localhost"),
    delay_between_requests=0.0,
    timeout=3.0,
)


class FetchCase(WorkspaceCase):
    def setUp(self):
        super().setUp()
        self.server = TestServer(slow_seconds=5.0)
        self.server.__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.store = Store(self.ws.state_db)
        self.addCleanup(self.store.close)
        self.slept: list[float] = []

    def config(self, **overrides):
        return fetch.FetchConfig(**{**LOCAL_CONFIG, **overrides})

    def fetcher(self, **overrides):
        return fetch.Fetcher(self.config(**overrides), store=self.store,
                             sleep=self.slept.append)

    def url(self, path):
        return self.server.base_url + path

    def rewrite_corpus_to_local(self):
        """Point the demo fixture's placeholder host at the live test server."""
        raw = json.loads(self.ws.corpus_file.read_text(encoding="utf-8"))
        for work in raw["works"]:
            for asset in work["assets"]:
                asset["url"] = asset["url"].replace("https://fixtures.invalid",
                                                    self.server.base_url)
        util.write_json_atomic(self.ws.corpus_file, raw)
        return model.load_corpus(self.ws.corpus_file)


class TestUrlPolicy(unittest.TestCase):
    def test_non_http_scheme_refused(self):
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.check_url("ftp://example.org/x", fetch.FetchConfig())
        self.assertEqual(caught.exception.kind, "policy")

    def test_plain_http_refused_by_default(self):
        with self.assertRaises(fetch.FetchError):
            fetch.check_url("http://example.org/x", fetch.FetchConfig())

    def test_embedded_credentials_refused(self):
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.check_url("https://u:p@example.org/x", fetch.FetchConfig())
        self.assertIn("credentials", caught.exception.reason)

    def test_private_address_refused_unless_allowlisted(self):
        with self.assertRaises(fetch.FetchError):
            fetch.check_url("https://127.0.0.1/x", fetch.FetchConfig())
        allowed = fetch.FetchConfig(allow_private_hosts=("127.0.0.1",))
        fetch.check_url("https://127.0.0.1/x", allowed)  # must not raise


class TestSuccessPath(FetchCase):
    def test_valid_pdf_is_accepted_and_hashed(self):
        response = self.fetcher().fetch(self.url("/paper.pdf"), "application/pdf")
        self.addCleanup(response.body_path.unlink, True)
        self.assertEqual(response.status, 200)
        self.assertEqual(len(response.sha256), 64)
        self.assertTrue(response.body_path.read_bytes().startswith(b"%PDF-"))

    def test_redirect_hops_are_recorded(self):
        response = self.fetcher().fetch(self.url("/redirect-ok"), "application/pdf")
        self.addCleanup(response.body_path.unlink, True)
        self.assertEqual(len(response.redirects), 1)
        self.assertEqual(response.redirects[0]["status"], 302)
        self.assertTrue(response.final_url.endswith("/paper.pdf"))


class TestIntegrityFailures(FetchCase):
    def assert_integrity(self, path, expected="application/pdf"):
        with self.assertRaises(fetch.FetchError) as caught:
            self.fetcher().fetch(self.url(path), expected)
        self.assertEqual(caught.exception.kind, "integrity",
                         msg=f"{path}: {caught.exception.reason}")
        return caught.exception

    def test_html_login_served_as_pdf_is_an_integrity_failure(self):
        exc = self.assert_integrity("/login-as-pdf.pdf")
        self.assertIn("HTML page", exc.reason)

    def test_mislabeled_body_without_magic_bytes_is_rejected(self):
        self.assert_integrity("/mislabeled.pdf")

    def test_truncated_body_is_rejected(self):
        exc = self.assert_integrity("/truncated.pdf")
        self.assertIn("truncated", exc.reason)

    def test_undersized_body_is_rejected(self):
        exc = self.assert_integrity("/tiny.pdf")
        self.assertIn("minimum", exc.reason)

    def test_oversized_body_is_rejected(self):
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.Fetcher(self.config(max_bytes=1024), store=self.store,
                          sleep=self.slept.append).fetch(self.url("/huge.pdf"),
                                                         "application/pdf")
        self.assertEqual(caught.exception.kind, "integrity")

    def test_no_partial_file_is_left_behind(self):
        before = set(Path("/tmp").glob("*.part"))
        with self.assertRaises(fetch.FetchError):
            self.fetcher().fetch(self.url("/login-as-pdf.pdf"), "application/pdf")
        self.assertEqual(set(Path("/tmp").glob("*.part")) - before, set())


class TestAvailabilityFailures(FetchCase):
    def test_403_is_recorded_and_not_retried(self):
        with self.assertRaises(fetch.FetchError) as caught:
            self.fetcher().fetch(self.url("/forbidden.pdf"), "application/pdf")
        self.assertEqual(caught.exception.http_status, 403)
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(self.server.counters["/forbidden.pdf"], 1)

    def test_404_is_not_retried(self):
        with self.assertRaises(fetch.FetchError):
            self.fetcher().fetch(self.url("/notfound.pdf"), "application/pdf")
        self.assertEqual(self.server.counters["/notfound.pdf"], 1)

    def test_timeout_is_retried_then_fails(self):
        fetcher = fetch.Fetcher(self.config(timeout=0.3, max_attempts=2),
                                store=self.store, sleep=self.slept.append)
        with self.assertRaises(fetch.FetchError) as caught:
            fetcher.fetch(self.url("/slow.pdf"), "application/pdf")
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(len(self.slept), 1)

    def test_redirect_loop_is_bounded(self):
        with self.assertRaises(fetch.FetchError) as caught:
            self.fetcher().fetch(self.url("/redirect-loop"), "text/html")
        self.assertIn("redirect chain exceeded", caught.exception.reason)

    def test_redirect_without_location_fails(self):
        with self.assertRaises(fetch.FetchError) as caught:
            self.fetcher().fetch(self.url("/redirect-no-location"), "text/html")
        self.assertIn("without Location", caught.exception.reason)

    def test_429_is_retried_honouring_retry_after(self):
        fetcher = fetch.Fetcher(self.config(max_attempts=4), store=self.store,
                                sleep=self.slept.append)
        response = fetcher.fetch(self.url("/ratelimited.pdf"), "application/pdf")
        self.addCleanup(response.body_path.unlink, True)
        self.assertEqual(response.status, 200)
        # Two 429s, each with Retry-After: 1, so two one-second waits.
        self.assertEqual(self.slept, [1.0, 1.0])

    def test_5xx_is_retried_up_to_the_attempt_limit(self):
        fetcher = fetch.Fetcher(self.config(max_attempts=3), store=self.store,
                                sleep=self.slept.append)
        with self.assertRaises(fetch.FetchError):
            fetcher.fetch(self.url("/servererror.pdf"), "application/pdf")
        self.assertEqual(self.server.counters["/servererror.pdf"], 3)


class TestRetryAfterParsing(unittest.TestCase):
    def test_integer_seconds(self):
        self.assertEqual(fetch.parse_retry_after("30"), 30.0)

    def test_http_date_is_converted_to_a_delay(self):
        self.assertIsNotNone(fetch.parse_retry_after("Wed, 21 Oct 2099 07:28:00 GMT"))

    def test_garbage_returns_none(self):
        self.assertIsNone(fetch.parse_retry_after("soon"))
        self.assertIsNone(fetch.parse_retry_after(None))


class TestRobots(FetchCase):
    def test_disallowed_path_is_refused(self):
        allowed, reason = self.fetcher().robots_allows(self.url("/blocked/x.html"))
        self.assertFalse(allowed)
        self.assertIn("disallowed", reason)

    def test_allowed_path_passes(self):
        allowed, _ = self.fetcher().robots_allows(self.url("/paper.pdf"))
        self.assertTrue(allowed)

    def test_robots_is_fetched_once_per_origin(self):
        fetcher = self.fetcher()
        fetcher.robots_allows(self.url("/paper.pdf"))
        fetcher.robots_allows(self.url("/a1.html"))
        self.assertEqual(self.server.counters["/robots.txt"], 1)

    def test_robots_is_never_read_with_the_unbounded_helper(self):
        # RobotFileParser.read() has no timeout or size cap; it must not be used.
        source = Path(fetch.__file__).read_text(encoding="utf-8")
        self.assertNotIn(".read()", source.split("def _load_robots")[1].split("def ")[0])


class TestCorpusAcquisition(FetchCase):
    def run_fetch(self, **kwargs):
        corpus = self.rewrite_corpus_to_local()
        return corpus, fetch.fetch_corpus(
            self.ws, corpus, self.store, self.config(),
            fetcher=self.fetcher(), run_id="testrun", **kwargs)

    def test_intents_map_to_distinct_statuses(self):
        _corpus, outcomes = self.run_fetch()
        by_asset = {o.asset_id: o for o in outcomes}
        self.assertEqual(by_asset["d-r0-fulltext"].status, fetch.STATUS_DOWNLOADED)
        self.assertEqual(by_asset["d-a1-landing"].status, fetch.STATUS_METADATA_ONLY)
        self.assertEqual(by_asset["d-book-preview"].status, fetch.STATUS_MANUAL_REQUIRED)

    def test_purchase_only_work_is_never_stored_locally(self):
        _corpus, outcomes = self.run_fetch()
        book = [o for o in outcomes if o.alias == "D-BOOK"]
        self.assertTrue(all(o.status != fetch.STATUS_DOWNLOADED for o in book))
        self.assertFalse(any((self.ws.raw / "D-BOOK").glob("*"))
                         if (self.ws.raw / "D-BOOK").exists() else False)

    def test_artifacts_land_at_deterministic_paths_with_matching_hashes(self):
        _corpus, outcomes = self.run_fetch()
        downloaded = [o for o in outcomes if o.status == fetch.STATUS_DOWNLOADED]
        self.assertTrue(downloaded)
        for outcome in downloaded:
            path = self.ws.root / outcome.path
            self.assertTrue(path.exists(), outcome.path)
            self.assertEqual(util.sha256_file(path), outcome.sha256)
            row = self.store.get_artifact(outcome.asset_id)
            self.assertEqual(row["sha256"], outcome.sha256)

    def test_rerun_makes_no_unnecessary_request(self):
        corpus, _ = self.run_fetch()
        first = dict(self.server.counters)
        fetch.fetch_corpus(self.ws, corpus, self.store, self.config(),
                           fetcher=self.fetcher(), run_id="testrun2")
        self.assertEqual(self.server.counters["/r0.html"], first["/r0.html"])

    def test_report_distinguishes_every_status(self):
        _corpus, outcomes = self.run_fetch()
        summary = fetch.summarize(outcomes)
        self.assertEqual(
            set(summary["counts"]),
            {fetch.STATUS_DOWNLOADED, fetch.STATUS_METADATA_ONLY,
             fetch.STATUS_MANUAL_REQUIRED},
        )

    def test_require_fulltext_all_exits_two_while_gated_items_remain(self):
        corpus, outcomes = self.run_fetch()
        self.assertEqual(fetch.exit_code_for(outcomes, corpus=corpus), util.EXIT_OK)
        # D-BOOK is purchase-only: it has no fulltext asset at all, so it is
        # counted as a gated work rather than quietly passing.
        summary = fetch.summarize(outcomes, corpus)
        self.assertEqual(summary["works_without_fulltext"], ["D-BOOK"])
        self.assertEqual(
            fetch.exit_code_for(outcomes, require_fulltext_all=True, corpus=corpus),
            util.EXIT_INCOMPLETE,
        )

    def test_a_failed_required_asset_yields_exit_two(self):
        raw = json.loads(self.ws.corpus_file.read_text(encoding="utf-8"))
        raw["works"][0]["assets"][0]["url"] = self.url("/forbidden.pdf")
        raw["works"][0]["assets"][0]["expected_media_type"] = "application/pdf"
        util.write_json_atomic(self.ws.corpus_file, raw)
        corpus = self.rewrite_corpus_to_local()
        outcomes = fetch.fetch_corpus(self.ws, corpus, self.store, self.config(),
                                      fetcher=self.fetcher(), run_id="t")
        self.assertEqual(fetch.exit_code_for(outcomes), util.EXIT_INCOMPLETE)

    def test_an_integrity_failure_yields_exit_four(self):
        raw = json.loads(self.ws.corpus_file.read_text(encoding="utf-8"))
        raw["works"][0]["assets"][0]["url"] = self.url("/login-as-pdf.pdf")
        raw["works"][0]["assets"][0]["expected_media_type"] = "application/pdf"
        util.write_json_atomic(self.ws.corpus_file, raw)
        corpus = self.rewrite_corpus_to_local()
        outcomes = fetch.fetch_corpus(self.ws, corpus, self.store, self.config(),
                                      fetcher=self.fetcher(), run_id="t")
        self.assertEqual(fetch.exit_code_for(outcomes), util.EXIT_INTEGRITY)


class TestManualImport(FetchCase):
    def test_import_records_user_supplied_provenance(self):
        corpus = self.rewrite_corpus_to_local()
        source = self.root / "supplied.pdf"
        source.write_bytes(
            (Path(__file__).resolve().parent / "fixtures" / "demo" / "www" / "paper.pdf").read_bytes())
        outcome = fetch.import_local(self.ws, corpus, self.store, "D-BOOK", source)
        self.assertEqual(outcome.status, fetch.STATUS_DOWNLOADED)
        self.assertIn("user_supplied", outcome.reason)
        self.assertEqual(outcome.media_type, "application/pdf")
        self.assertTrue((self.ws.root / outcome.path).exists())
        self.assertIn("manual-import", outcome.path)

    def test_import_of_unknown_alias_is_refused(self):
        corpus = self.rewrite_corpus_to_local()
        with self.assertRaises(fetch.FetchError):
            fetch.import_local(self.ws, corpus, self.store, "NOPE", Path(__file__))
