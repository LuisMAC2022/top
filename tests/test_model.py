"""Manifest validation: the gate that must fail before any network use."""

import copy
import json
import unittest
from pathlib import Path

from bibgraph import model, util

from .support import DEMO, WorkspaceCase


def load_demo():
    return json.loads((DEMO / "config" / "corpus.json").read_text(encoding="utf-8"))


def load_demo_deps():
    return json.loads((DEMO / "config" / "dependencies.json").read_text(encoding="utf-8"))


class ValidatorCase(WorkspaceCase):
    def write_corpus(self, raw):
        util.write_json_atomic(self.ws.corpus_file, raw)

    def write_deps(self, raw):
        util.write_json_atomic(self.ws.dependencies_file, raw)

    def codes(self, severity="error"):
        corpus, deps, profile, issues = __import__(
            "bibgraph.checks", fromlist=["x"]
        ).load_and_validate(self.ws)
        return {i.code for i in issues if i.severity == severity}


class TestDemoFixtureIsClean(ValidatorCase):
    def test_demo_has_no_errors(self):
        self.assertEqual(self.codes("error"), set())

    def test_demo_reports_unresolved_choice_as_warning(self):
        self.assertIn("choice-unselected", self.codes("warning"))


class TestCorpusRules(ValidatorCase):
    def test_duplicate_alias_is_error(self):
        raw = load_demo()
        raw["works"][1]["aliases"] = ["D-R0"]
        self.write_corpus(raw)
        self.assertIn("duplicate-alias", self.codes())

    def test_duplicate_work_id_is_error(self):
        raw = load_demo()
        raw["works"][1]["id"] = raw["works"][0]["id"]
        self.write_corpus(raw)
        self.assertIn("duplicate-work-id", self.codes())

    def test_unknown_role_is_error(self):
        raw = load_demo()
        raw["works"][0]["assets"][0]["role"] = "sideways"
        self.write_corpus(raw)
        self.assertIn("bad-role", self.codes())

    def test_unknown_intent_is_error(self):
        raw = load_demo()
        raw["works"][0]["assets"][0]["intent"] = "maybe"
        self.write_corpus(raw)
        self.assertIn("bad-intent", self.codes())

    def test_asset_without_url_is_error(self):
        raw = load_demo()
        raw["works"][0]["assets"][0]["url"] = None
        self.write_corpus(raw)
        self.assertIn("missing-url", self.codes())

    def test_non_http_scheme_is_error(self):
        raw = load_demo()
        raw["works"][0]["assets"][0]["url"] = "file:///etc/passwd"
        self.write_corpus(raw)
        self.assertIn("bad-url-scheme", self.codes())

    def test_missing_expected_alias_is_error(self):
        raw = load_demo()
        raw["works"] = raw["works"][1:]
        self.write_corpus(raw)
        self.assertIn("missing-seed-alias", self.codes())

    def test_publish_fulltext_without_licence_evidence_is_error(self):
        raw = load_demo()
        raw["works"][0]["rights"]["publish_fulltext"] = True
        self.write_corpus(raw)
        self.assertIn("publish-without-evidence", self.codes())

    def test_publish_abstract_without_licence_evidence_is_error(self):
        raw = load_demo()
        raw["works"][0]["rights"]["publish_abstract"] = True
        self.write_corpus(raw)
        self.assertIn("publish-without-evidence", self.codes())

    def test_verified_metadata_requires_a_title(self):
        raw = load_demo()
        raw["works"][0]["title"] = ""
        raw["works"][0]["title_status"] = "unknown"
        self.write_corpus(raw)
        self.assertIn("unverifiable-metadata", self.codes())

    def test_collection_without_members_is_error(self):
        raw = load_demo()
        for work in raw["works"]:
            if work["work_type"] == "collection":
                work["members"] = []
        self.write_corpus(raw)
        self.assertIn("empty-collection", self.codes())

    def test_dangling_container_is_error(self):
        raw = load_demo()
        for work in raw["works"]:
            if work["container"]:
                work["container"] = "NOPE"
        self.write_corpus(raw)
        self.assertIn("dangling-container", self.codes())


class TestDependencyRules(ValidatorCase):
    def test_dangling_edge_endpoint_is_error(self):
        raw = load_demo_deps()
        raw["edges"].append({"from": "D-R0", "to": "GHOST", "type": "prerequisite"})
        self.write_deps(raw)
        self.assertIn("dangling-edge-endpoint", self.codes())

    def test_unknown_edge_type_is_error(self):
        raw = load_demo_deps()
        raw["edges"][0]["type"] = "vibes"
        self.write_deps(raw)
        self.assertIn("bad-edge-type", self.codes())

    def test_duplicate_edge_is_error(self):
        raw = load_demo_deps()
        raw["edges"].append(copy.deepcopy(raw["edges"][0]))
        self.write_deps(raw)
        self.assertIn("duplicate-edge", self.codes())

    def test_self_edge_is_error(self):
        raw = load_demo_deps()
        raw["edges"].append({"from": "D-R0", "to": "D-R0", "type": "prerequisite"})
        self.write_deps(raw)
        self.assertIn("self-edge", self.codes())

    def test_ordering_cycle_is_error(self):
        raw = load_demo_deps()
        raw["edges"].append({"from": "D-PDF", "to": "D-R0", "type": "prerequisite"})
        self.write_deps(raw)
        self.assertIn("dependency-cycle", self.codes())

    def test_backup_edge_may_close_a_loop(self):
        # backup/validates are not ordering edges, so they are allowed to cycle.
        raw = load_demo_deps()
        raw["edges"].append({"from": "D-A2", "to": "D-A3", "type": "backup"})
        self.write_deps(raw)
        self.assertNotIn("dependency-cycle", self.codes())

    def test_choice_with_one_option_is_error(self):
        raw = load_demo_deps()
        for node in raw["nodes"]:
            if node["kind"] == "choice":
                node["options"] = ["D-A2"]
        self.write_deps(raw)
        self.assertIn("degenerate-choice", self.codes())

    def test_choice_option_must_be_a_node(self):
        raw = load_demo_deps()
        for node in raw["nodes"]:
            if node["kind"] == "choice":
                node["options"] = ["D-A2", "GHOST"]
        self.write_deps(raw)
        self.assertIn("dangling-choice-option", self.codes())

    def test_dangling_node_ref_is_error(self):
        raw = load_demo_deps()
        raw["nodes"][0]["ref"] = "local:nothing"
        self.write_deps(raw)
        self.assertIn("dangling-ref", self.codes())


class TestReadingProfile(ValidatorCase):
    def test_selecting_a_non_option_is_error(self):
        util.write_json_atomic(self.ws.profile_file, {
            "schema_version": "1.0", "name": "t",
            "selections": {"choice:demo-text": "D-R0"}})
        self.assertIn("bad-choice-selection", self.codes())

    def test_selecting_an_unknown_choice_is_error(self):
        util.write_json_atomic(self.ws.profile_file, {
            "schema_version": "1.0", "name": "t",
            "selections": {"choice:ghost": None}})
        self.assertIn("unknown-choice", self.codes())

    def test_a_valid_selection_clears_the_warning(self):
        util.write_json_atomic(self.ws.profile_file, {
            "schema_version": "1.0", "name": "t",
            "selections": {"choice:demo-text": "D-A2"}})
        self.assertNotIn("choice-unselected", self.codes("warning"))


class TestProjectManifest(unittest.TestCase):
    """The checked-in config must itself validate."""

    def test_repository_config_validates(self):
        from bibgraph import checks

        ws = util.Workspace.from_root(Path(__file__).resolve().parent.parent)
        _corpus, _deps, _profile, issues = checks.load_and_validate(ws)
        self.assertEqual([str(i) for i in model.errors(issues)], [])

    def test_repository_config_accounts_for_all_twenty_seeds(self):
        corpus = model.load_corpus(
            Path(__file__).resolve().parent.parent / "config" / "corpus.json")
        aliases = set(corpus.all_aliases())
        self.assertTrue(set(model.SEED_ALIASES).issubset(aliases))
        self.assertEqual(len(model.SEED_ALIASES), 20)

    def test_a5_is_modelled_as_a_collection_of_four(self):
        corpus = model.load_corpus(
            Path(__file__).resolve().parent.parent / "config" / "corpus.json")
        a5 = corpus.by_alias()["A5"]
        self.assertEqual(a5.work_type, "collection")
        self.assertEqual(len(a5.members), 4)
        children = [w for w in corpus.works if w.container == "A5"]
        self.assertEqual(len(children), 4)
        self.assertTrue(all(c.work_type == "sequence" for c in children))

    def test_both_documented_choices_are_present_and_unselected(self):
        root = Path(__file__).resolve().parent.parent
        deps = model.load_dependencies(root / "config" / "dependencies.json")
        profile = model.load_reading_profile(root / "config" / "reading-profile.json")
        choices = {n.id: n for n in deps.nodes if n.kind == "choice"}
        self.assertEqual(sorted(choices), ["choice:enumeration-text", "choice:proof-foundation"])
        self.assertEqual(sorted(choices["choice:proof-foundation"].options), ["A7", "C2"])
        self.assertEqual(sorted(choices["choice:enumeration-text"].options), ["A2", "A3"])
        self.assertTrue(all(v is None for v in profile.values()))


class TestExitCodePrecedence(unittest.TestCase):
    def test_manifest_error_outranks_integrity_and_incomplete(self):
        self.assertEqual(util.resolve_exit_code([2, 3, 4]), 3)

    def test_integrity_outranks_incomplete(self):
        self.assertEqual(util.resolve_exit_code([2, 4]), 4)

    def test_empty_is_success(self):
        self.assertEqual(util.resolve_exit_code([]), 0)
