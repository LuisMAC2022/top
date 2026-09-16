"""Resolution precision, and the graph invariants that depend on it."""

import json
import unittest
from pathlib import Path

from bibgraph import analysis, graph, model, references, resolve, util

from .support import DEMO, WorkspaceCase

CASES = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "resolution" / "cases.json")
    .read_text(encoding="utf-8"))


def demo_corpus_with_dois():
    corpus = model.load_corpus(DEMO / "config" / "corpus.json")
    for work in corpus.works:
        if work.primary_alias == "D-A2":
            work.identifiers = {"doi": "10.1016/j.demo.2021.01.002"}
        if work.primary_alias == "D-A3":
            work.identifiers = {"doi": "10.1016/j.demo.2021.01.003"}
    return corpus


class TestResolutionPrecision(unittest.TestCase):
    """The plan's gate: at least 98% precision on auto-accepted matches."""

    def setUp(self):
        self.corpus = demo_corpus_with_dois()
        self.index = resolve.LocalIndex(self.corpus)
        self.by_id = {w.id: w for w in self.corpus.works}
        self.citing = self.corpus.works[0]

    def resolve_case(self, raw):
        parsed = references.parse_reference(1, raw)
        return resolve.resolve_reference(self.citing, parsed, self.index)

    def test_auto_accepted_matches_are_at_least_98_percent_precise(self):
        accepted = 0
        correct = 0
        wrong = []
        for case in CASES["cases"]:
            result = self.resolve_case(case["raw"])
            if result.status != resolve.STATUS_RESOLVED:
                continue
            accepted += 1
            alias = self.by_id[result.target_id].primary_alias \
                if result.target_id in self.by_id else None
            if alias == case["expect"]:
                correct += 1
            else:
                wrong.append((case["raw"], case["expect"], alias, case["why"]))
        self.assertGreater(accepted, 0, "no case auto-accepted; the gate is vacuous")
        precision = correct / accepted
        self.assertGreaterEqual(precision, 0.98, f"wrong: {wrong}")

    def test_every_case_labelled_resolvable_is_resolved(self):
        for case in CASES["cases"]:
            if case["expect"] is None:
                continue
            with self.subTest(why=case["why"]):
                result = self.resolve_case(case["raw"])
                self.assertEqual(result.status, resolve.STATUS_RESOLVED,
                                 f"{case['raw']}: {result.reason}")
                self.assertEqual(self.by_id[result.target_id].primary_alias,
                                 case["expect"])

    def test_no_case_labelled_unresolvable_is_auto_accepted(self):
        for case in CASES["cases"]:
            if case["expect"] is not None:
                continue
            with self.subTest(why=case["why"]):
                result = self.resolve_case(case["raw"])
                if result.status == resolve.STATUS_RESOLVED:
                    alias = self.by_id.get(result.target_id)
                    self.fail(f"{case['raw']!r} wrongly merged into "
                              f"{alias.primary_alias if alias else result.target_id}")

    def test_a_near_miss_title_is_queued_not_merged(self):
        result = self.resolve_case(
            "C. Duarte. Enumeration by Transfer Matrices. J. Demo, 2021.")
        self.assertIn(result.status, (resolve.STATUS_AMBIGUOUS,
                                      resolve.STATUS_DISCOVERED))
        self.assertNotEqual(result.target_id, self.corpus.by_alias()["D-A2"].id)

    def test_every_resolution_keeps_its_candidate_evidence(self):
        result = self.resolve_case(
            "Duarte, C. Enumeration by Transfer Matrix. Journal of Demonstration, 2021.")
        self.assertTrue(result.candidates)
        for candidate in result.candidates:
            self.assertIn("score", candidate.as_dict())
            self.assertTrue(candidate.as_dict()["evidence"])

    def test_the_raw_string_survives_into_the_resolution(self):
        raw = "[1] Duarte, C. Enumeration by Transfer Matrix. 2021."
        self.assertEqual(self.resolve_case(raw).raw, raw)

    def test_a_tie_between_two_works_is_ambiguous_not_arbitrary(self):
        corpus = demo_corpus_with_dois()
        # Two works claiming the same title and year is a genuine ambiguity.
        corpus.works[1].title = corpus.works[2].title
        corpus.works[1].year = corpus.works[2].year
        index = resolve.LocalIndex(corpus)
        parsed = references.parse_reference(
            1, f"{corpus.works[2].title}. {corpus.works[2].year}.")
        result = resolve.resolve_reference(corpus.works[0], parsed, index)
        self.assertNotEqual(result.status, resolve.STATUS_RESOLVED)


class TestCrossrefScoring(unittest.TestCase):
    def score(self, raw, item):
        return resolve.score_crossref_item(references.parse_reference(1, raw), item)

    def test_a_strong_match_scores_high_but_never_certain(self):
        score, _ = self.score(
            "R. Stanley. On the number of open sets of finite topologies. 1971.",
            {"title": ["On the number of open sets of finite topologies"],
             "issued": {"date-parts": [[1971]]},
             "author": [{"family": "Stanley"}], "DOI": "10.1/x"})
        self.assertGreater(score, 0.85)
        self.assertLess(score, 1.0)

    def test_a_wrong_year_is_penalised(self):
        strong, _ = self.score(
            "R. Stanley. On the number of open sets of finite topologies. 1971.",
            {"title": ["On the number of open sets of finite topologies"],
             "issued": {"date-parts": [[1971]]}, "author": [{"family": "Stanley"}]})
        weak, _ = self.score(
            "R. Stanley. On the number of open sets of finite topologies. 1971.",
            {"title": ["On the number of open sets of finite topologies"],
             "issued": {"date-parts": [[1994]]}, "author": [{"family": "Stanley"}]})
        self.assertLess(weak, strong)

    def test_an_unrelated_title_scores_near_zero(self):
        score, _ = self.score("A. Author. Completely Different Words. 2001.",
                              {"title": ["Nothing At All Alike"],
                               "issued": {"date-parts": [[2001]]}})
        self.assertLess(score, 0.5)

    def test_scoring_never_reaches_auto_accept_on_title_alone(self):
        score, _ = self.score("Enumeration by Transfer Matrix.",
                              {"title": ["Enumeration by Transfer Matrix"]})
        self.assertLess(score, resolve.AUTO_ACCEPT)


class TestGraphInvariants(unittest.TestCase):
    def edges(self, pairs):
        return [{"type": "citation", "source": s, "target": t, "weight": 1}
                for s, t in pairs]

    def test_citation_direction_is_citing_to_cited(self):
        resolutions = [resolve.Resolution(
            citing_work_id="A", citing_alias="A", reference_index=1, raw="raw",
            parsed={}, status="resolved", target_id="B", method="local-doi",
            confidence=1.0, candidates=[])]
        edge = graph.citation_edges(resolutions)[0]
        self.assertEqual((edge["source"], edge["target"]), ("A", "B"))

    def test_no_citation_edge_lacks_a_raw_reference_and_evidence(self):
        resolutions = [resolve.Resolution(
            citing_work_id="A", citing_alias="A", reference_index=i, raw=f"raw {i}",
            parsed={}, status="resolved", target_id="B", method="local-doi",
            confidence=1.0,
            candidates=[resolve.Candidate("B", "local-doi", 1.0, {"doi": "10.1/x"})])
            for i in (1, 2)]
        for edge in graph.citation_edges(resolutions):
            self.assertTrue(edge["raw_references"])
            self.assertTrue(edge["evidence"])
            self.assertIsNotNone(edge["method"])

    def test_duplicate_citations_collapse_deterministically(self):
        resolutions = [resolve.Resolution(
            citing_work_id="A", citing_alias="A", reference_index=i, raw=f"raw {i}",
            parsed={}, status="resolved", target_id="B", method="local-doi",
            confidence=1.0, candidates=[]) for i in (1, 2, 3)]
        edges = graph.citation_edges(resolutions)
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["weight"], 3)
        self.assertEqual(edges[0]["raw_references"], ["raw 1", "raw 2", "raw 3"])

    def test_unresolved_references_produce_no_edge(self):
        resolutions = [resolve.Resolution(
            citing_work_id="A", citing_alias="A", reference_index=1, raw="raw",
            parsed={}, status="ambiguous", target_id=None, method=None,
            confidence=0.5, candidates=[])]
        self.assertEqual(graph.citation_edges(resolutions), [])

    def test_coupling_is_symmetric_and_self_free(self):
        edges = self.edges([("A", "X"), ("A", "Y"), ("B", "X"), ("B", "Y")])
        coupling = graph.bibliographic_coupling(edges)
        self.assertEqual(len(coupling), 1)
        self.assertEqual(coupling[0]["shared"], 2)
        self.assertNotEqual(coupling[0]["a"], coupling[0]["b"])

    def test_cosine_normalisation_penalises_a_long_bibliography(self):
        # B cites everything; it must not look closest to everyone.
        edges = self.edges([("A", "X"), ("A", "Y")]
                           + [("B", n) for n in "XYZWVUTS"])
        coupling = {(e["a"], e["b"]): e for e in graph.bibliographic_coupling(edges)}
        pair = coupling[("A", "B")]
        self.assertEqual(pair["shared"], 2)
        self.assertLess(pair["cosine"], 1.0)
        self.assertAlmostEqual(pair["cosine"], 2 / (2 * 8) ** 0.5, places=6)

    def test_coupling_respects_the_minimum_shared_threshold(self):
        edges = self.edges([("A", "X"), ("B", "X")])
        self.assertEqual(graph.bibliographic_coupling(edges, min_shared=2), [])
        self.assertEqual(len(graph.bibliographic_coupling(edges, min_shared=1)), 1)

    def test_co_citation_counts_works_citing_both(self):
        edges = self.edges([("A", "X"), ("A", "Y"), ("B", "X"), ("B", "Y")])
        pairs = graph.co_citation(edges, min_shared=2)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["shared"], 2)
        self.assertEqual(pairs[0]["cited_by"], ["A", "B"])

    def test_pagerank_conserves_probability(self):
        edges = self.edges([("A", "B"), ("B", "C"), ("C", "A"), ("A", "C")])
        ranks = graph.pagerank(edges)
        self.assertAlmostEqual(sum(ranks.values()), 1.0, places=9)

    def test_pagerank_handles_sinks_without_leaking(self):
        # D cites nothing: a naive implementation loses its mass every round.
        edges = self.edges([("A", "D"), ("B", "D"), ("C", "D")])
        ranks = graph.pagerank(edges)
        self.assertAlmostEqual(sum(ranks.values()), 1.0, places=9)
        self.assertGreater(ranks["D"], ranks["A"])

    def test_pagerank_tolerates_a_cycle(self):
        edges = self.edges([("A", "B"), ("B", "A")])
        ranks = graph.pagerank(edges)
        self.assertAlmostEqual(sum(ranks.values()), 1.0, places=9)
        self.assertAlmostEqual(ranks["A"], ranks["B"], places=9)

    def test_pagerank_is_empty_for_an_empty_graph(self):
        self.assertEqual(graph.pagerank([]), {})

    def test_citation_graph_may_cycle_while_the_dependency_dag_may_not(self):
        edges = self.edges([("A", "B"), ("B", "A")])
        self.assertEqual(len(graph.citation_indegree(edges)), 2)
        deps = model.Dependencies(
            nodes=[model.Node("A", "work", "A", "A"), model.Node("B", "work", "B", "B")],
            edges=[model.Edge("A", "B", "prerequisite"),
                   model.Edge("B", "A", "prerequisite")])
        self.assertIsNotNone(model.find_cycle(deps))


class TestDiscoveryAndExpansion(WorkspaceCase):
    def test_discovery_creates_metadata_only_nodes_not_downloads(self):
        corpus = demo_corpus_with_dois()
        index = resolve.LocalIndex(corpus)
        parsed = references.parse_reference(
            1, "P. Alexandroff. Diskrete Raume. Mat. Sbornik, 1937.")
        result = resolve.resolve_reference(corpus.works[0], parsed, index)
        self.assertEqual(result.status, resolve.STATUS_DISCOVERED)
        self.assertIn("not queued for download", result.reason)

    def test_the_same_work_cited_with_and_without_a_doi_merges(self):
        records = {
            "doi:10.1/x": {"id": "doi:10.1/x", "title": "A Shared Title", "year": 1971,
                           "authors": ["R. Stanley"], "doi": "10.1/x", "isbn": None,
                           "cited_by": ["A"], "raw_references": ["with doi"],
                           "origin": "discovered", "acquisition": "not_requested"},
            "local:abc": {"id": "local:abc", "title": "A Shared Title", "year": 1971,
                          "authors": ["Stanley, R."], "doi": None, "isbn": None,
                          "cited_by": ["B"], "raw_references": ["without doi"],
                          "origin": "discovered", "acquisition": "not_requested"},
        }
        merged, alias = analysis.merge_discovered(records)
        self.assertEqual(len(merged), 1)
        # The identifier-bearing id wins, and the merge is recorded.
        self.assertIn("doi:10.1/x", merged)
        self.assertEqual(alias["local:abc"], "doi:10.1/x")
        self.assertEqual(merged["doi:10.1/x"]["cited_by"], ["A", "B"])
        self.assertTrue(merged["doi:10.1/x"]["merged_from"])

    def test_a_different_year_blocks_the_merge(self):
        records = {
            "a": {"id": "a", "title": "Same Title", "year": 1971, "authors": ["X. Y"],
                  "doi": None, "isbn": None, "cited_by": [], "raw_references": [],
                  "origin": "discovered", "acquisition": "not_requested"},
            "b": {"id": "b", "title": "Same Title", "year": 1999, "authors": ["X. Y"],
                  "doi": None, "isbn": None, "cited_by": [], "raw_references": [],
                  "origin": "discovered", "acquisition": "not_requested"},
        }
        merged, _ = analysis.merge_discovered(records)
        self.assertEqual(len(merged), 2)

    def test_incomplete_records_are_never_merged(self):
        records = {
            "a": {"id": "a", "title": None, "year": None, "authors": [], "doi": None,
                  "isbn": None, "cited_by": [], "raw_references": [],
                  "origin": "discovered", "acquisition": "not_requested"},
            "b": {"id": "b", "title": None, "year": None, "authors": [], "doi": None,
                  "isbn": None, "cited_by": [], "raw_references": [],
                  "origin": "discovered", "acquisition": "not_requested"},
        }
        merged, _ = analysis.merge_discovered(records)
        self.assertEqual(len(merged), 2)

    def test_promotion_is_bounded_on_every_axis(self):
        discovered = {
            f"id{i}": {"id": f"id{i}", "title": f"T{i}", "year": 1990 + i,
                       "authors": ["A. B"], "doi": None, "isbn": None,
                       "cited_by": ["x"] * (i + 1), "raw_references": [],
                       "origin": "discovered", "acquisition": "not_requested"}
            for i in range(10)}
        fake = {"discovered": discovered}
        self.assertEqual(len(analysis.promotion_candidates(fake, 3, 1)), 3)
        self.assertTrue(all(len(c["cited_by"]) >= 5
                            for c in analysis.promotion_candidates(fake, 99, 5)))
        windowed = analysis.promotion_candidates(fake, 99, 1, year_from=1995, year_to=1997)
        self.assertTrue(all(1995 <= c["year"] <= 1997 for c in windowed))
