"""Survey, clustering, and the transparency requirements on ranking."""

import json
import unittest

from bibgraph import analysis as analysis_mod
from bibgraph import graph, model, survey, util

from .httpdouble import TestServer
from .support import DEMO, WorkspaceCase

RANKING = json.loads((DEMO / "config" / "ranking.json").read_text(encoding="utf-8"))


def citation(source, target):
    return {"type": "citation", "source": source, "target": target, "weight": 1,
            "method": "local-doi", "confidence": 1.0, "raw_references": ["r"],
            "evidence": []}


class TestTfIdf(unittest.TestCase):
    def test_a_term_common_to_every_document_does_not_discriminate(self):
        documents = {"a": "topology counting alpha", "b": "topology counting beta",
                     "c": "topology counting gamma"}
        scores = survey.tf_idf(documents, set())
        top = dict(scores["a"])
        self.assertGreater(top["alpha"], top.get("topology", 0))

    def test_stopwords_are_removed(self):
        scores = survey.tf_idf({"a": "the number of the finite topologies"},
                               {"the", "of"})
        self.assertNotIn("the", dict(scores["a"]))
        self.assertIn("finite", dict(scores["a"]))

    def test_an_empty_document_yields_no_terms(self):
        self.assertEqual(survey.tf_idf({"a": ""}, set())["a"], [])

    def test_scores_are_deterministic(self):
        documents = {"a": "finite topology enumeration", "b": "lattice counting"}
        self.assertEqual(survey.tf_idf(documents, set()),
                         survey.tf_idf(documents, set()))


class TestSeedGrouping(unittest.TestCase):
    def test_the_default_pattern_groups_the_seed_catalogue(self):
        self.assertEqual([survey.seed_group(a) for a in ("R0", "A1", "A7", "B6", "D1")],
                         ["R", "A", "A", "B", "D"])

    def test_a_collection_child_stays_with_its_parent_group(self):
        self.assertEqual(survey.seed_group("A5.1"), survey.seed_group("A5"))

    def test_the_pattern_is_corpus_declared(self):
        self.assertEqual(survey.seed_group("D-A1", r"^[A-Z]+-([A-Za-z]+)"), "A")

    def test_a_broken_pattern_falls_back_instead_of_raising(self):
        self.assertEqual(survey.seed_group("A1", "([unclosed"), "A")


class TestNormalisation(unittest.TestCase):
    def test_min_max_maps_to_the_unit_interval(self):
        self.assertEqual(survey.normalize({"a": 0.0, "b": 5.0, "c": 10.0}),
                         {"a": 0.0, "b": 0.5, "c": 1.0})

    def test_a_flat_dimension_contributes_nothing_rather_than_everything(self):
        self.assertEqual(survey.normalize({"a": 3.0, "b": 3.0}), {"a": 0.0, "b": 0.0})

    def test_an_empty_dimension_is_empty(self):
        self.assertEqual(survey.normalize({}), {})


class TestRanking(unittest.TestCase):
    def setUp(self):
        self.corpus = model.load_corpus(DEMO / "config" / "corpus.json")
        works = [w.id for w in self.corpus.works]
        self.edges = [citation(works[0], works[4]), citation(works[1], works[4]),
                      citation(works[2], works[4]), citation(works[0], works[3])]
        self.analysis = {
            "citation_edges": self.edges,
            "indegree": graph.citation_indegree(self.edges),
            "pagerank": graph.pagerank(self.edges),
            "coupling": graph.bibliographic_coupling(self.edges),
            "co_citation": [], "clusters": [], "discovered": {},
            "authorship_edges": graph.authorship_edges(self.corpus, {}),
            "cluster_threshold": 0.2,
        }

    def rank(self, config=None):
        return survey.rank_works(self.corpus, self.analysis, {}, config or RANKING)

    def test_dimensions_are_reported_separately(self):
        row = self.rank()[0]
        for dimension in survey.DIMENSIONS:
            self.assertIsNotNone(getattr(row, dimension), dimension)

    def test_every_number_is_traceable_to_the_works_that_produced_it(self):
        for row in self.rank():
            self.assertEqual(row.citation_indegree, len(row.citing_aliases),
                             f"{row.work_id}: indegree must match its citing list")

    def test_the_combined_score_only_exists_when_weights_are_published(self):
        without = survey.rank_works(self.corpus, self.analysis, {},
                                    {k: v for k, v in RANKING.items()
                                     if k != "reading_priority_weights"})
        self.assertTrue(all(r.score is None for r in without))
        self.assertTrue(all(r.score is not None for r in self.rank()))

    def test_ranking_is_reproducible_from_the_same_snapshot(self):
        self.assertEqual(util.canonical_json([r.as_dict() for r in self.rank()]),
                         util.canonical_json([r.as_dict() for r in self.rank()]))

    def test_external_citation_counts_are_absent_rather_than_assumed(self):
        self.assertTrue(all(r.external_cited_by is None for r in self.rank()))

    def test_sensitivity_covers_every_dimension_and_delta(self):
        rows = survey.sensitivity(self.rank(), RANKING["reading_priority_weights"],
                                  RANKING["sensitivity"]["weight_deltas"], 5)
        self.assertEqual(len(rows),
                         len(survey.DIMENSIONS) * len(RANKING["sensitivity"]["weight_deltas"]))
        for row in rows:
            self.assertIn("order_changed", row)
            self.assertIn("weights", row)

    def test_removing_the_top_work_produces_a_report_not_a_silent_change(self):
        rankings = self.rank()
        report = survey.leave_one_out(self.corpus, self.analysis, {}, RANKING,
                                      rankings[0].work_id)
        self.assertEqual(report["removed"], rankings[0].work_id)
        self.assertIn("top_before", report)
        self.assertIn("top_after", report)
        self.assertNotIn(report["removed"], report["top_after"])


class TestAuthorRanking(unittest.TestCase):
    def setUp(self):
        self.corpus = model.load_corpus(DEMO / "config" / "corpus.json")
        works = {w.primary_alias: w.id for w in self.corpus.works}
        self.edges = [citation(works["D-R0"], works["D-A3"]),
                      citation(works["D-A1"], works["D-A3"])]
        self.analysis = {
            "citation_edges": self.edges,
            "indegree": graph.citation_indegree(self.edges),
            "pagerank": graph.pagerank(self.edges),
            "coupling": graph.bibliographic_coupling(self.edges),
            "co_citation": [], "clusters": [], "discovered": {},
            "authorship_edges": graph.authorship_edges(self.corpus, {}),
            "cluster_threshold": 0.2,
        }
        self.work_rankings = survey.rank_works(self.corpus, self.analysis, {}, RANKING)
        self.authors = survey.rank_authors(self.corpus, self.analysis,
                                           self.work_rankings)

    def test_credit_is_divided_among_coauthors(self):
        # D-A3 has two authors and an indegree of 2, so each gets 1.0, not 2.0.
        by_name = {a.display_names[0]: a for a in self.authors}
        self.assertAlmostEqual(by_name["Cleo Duarte"].fractional_credit, 1.0, places=6)
        self.assertLess(by_name["Cleo Duarte"].fractional_credit, 2.0)

    def test_a_normalised_name_is_only_a_candidate_identity(self):
        for author in self.authors:
            self.assertLess(author.identity_confidence, 1.0)
            self.assertIn("name", author.identity_basis)
            self.assertIsNone(author.orcid)

    def test_name_collisions_are_reported(self):
        analysis = dict(self.analysis)
        analysis["authorship_edges"] = self.analysis["authorship_edges"] + [{
            "source": "author:duarte x", "target": self.corpus.works[0].id,
            "type": "authorship", "position": 9, "author_display": "X. Duarte",
            "corresponding": None, "identity_confidence": 0.5,
            "identity_basis": "normalized-name"}]
        authors = survey.rank_authors(self.corpus, analysis, self.work_rankings)
        colliding = {a.author_id for a in authors if a.name_collisions}
        self.assertIn("author:duarte x", colliding)
        self.assertIn("author:duarte c", colliding)

    def test_raw_author_citation_totals_are_not_a_reported_dimension(self):
        fields = set(self.authors[0].as_dict())
        self.assertNotIn("total_citations", fields)
        self.assertIn("fractional_credit", fields)

    def test_coauthor_degree_is_recorded(self):
        by_name = {a.display_names[0]: a for a in self.authors}
        self.assertEqual(by_name["Cleo Duarte"].coauthor_degree, 1)


class TestClusters(unittest.TestCase):
    def test_clusters_are_named_neutrally_and_carry_their_evidence(self):
        corpus = model.load_corpus(DEMO / "config" / "corpus.json")
        works = [w.id for w in corpus.works]
        edges = [citation(works[0], "x"), citation(works[0], "y"),
                 citation(works[1], "x"), citation(works[1], "y")]
        coupling = graph.bibliographic_coupling(edges)
        analysis = {"citation_edges": edges, "coupling": coupling,
                    "clusters": graph.connected_components(coupling, 0.2),
                    "discovered": {}}
        clusters = survey.build_clusters(corpus, analysis, set())
        self.assertTrue(clusters)
        self.assertTrue(clusters[0]["name"].startswith("Cluster "))
        self.assertTrue(clusters[0]["strongest_pairs"])
        self.assertTrue(clusters[0]["strongest_pairs"][0]["shared_references"])


class TestSurveyPage(WorkspaceCase):
    def test_the_page_separates_computation_from_interpretation(self):
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
        self.run_cli("build-site", "--local")
        page = (self.root / "build/site/survey/index.html").read_text(encoding="utf-8")
        self.assertIn("Computed observations, not conclusions", page)
        self.assertIn("not assess proof validity", page)
        self.assertIn("score = ", page)                       # formula is published
        self.assertIn("Sensitivity of the shortlist", page)
        self.assertIn("Credit is fractional", page)
        self.assertIn("candidate identity, never a confirmed", page)

    def test_the_graph_page_labels_coupling_correctly(self):
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
        self.run_cli("build-site", "--local")
        page = (self.root / "build/site/graph/index.html").read_text(encoding="utf-8")
        self.assertIn("do not indicate", page)
        self.assertIn("agreement, influence direction, or correctness", page)
        # The paragraph wraps in the source, so match across the newline.
        self.assertIn("that needs a human", page)
        self.assertIn("second pass", page)
