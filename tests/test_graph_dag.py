"""Dependency DAG navigation: order, layering, choices and determinism."""

import unittest

from bibgraph import model
from bibgraph.graph import DagView

from .support import DEMO


def view(profile=None):
    deps = model.load_dependencies(DEMO / "config" / "dependencies.json")
    return DagView(deps, profile or {"choice:demo-text": None})


class TestOrder(unittest.TestCase):
    def test_topological_order_respects_every_prerequisite(self):
        v = view()
        order = v.topological_order()
        position = {n: i for i, n in enumerate(order)}
        for edge in v.deps.ordering_edges():
            self.assertLess(position[edge.source], position[edge.target],
                            f"{edge.source} must precede {edge.target}")

    def test_topological_order_is_stable_across_runs(self):
        self.assertEqual(view().topological_order(), view().topological_order())

    def test_order_is_independent_of_declaration_order(self):
        deps = model.load_dependencies(DEMO / "config" / "dependencies.json")
        first = DagView(deps).topological_order()
        deps.nodes.reverse()
        deps.edges.reverse()
        self.assertEqual(DagView(deps).topological_order(), first)

    def test_a_cycle_is_reported_not_silently_truncated(self):
        deps = model.load_dependencies(DEMO / "config" / "dependencies.json")
        deps.edges.append(model.Edge("D-PDF", "D-R0", "prerequisite"))
        with self.assertRaises(ValueError):
            DagView(deps).topological_order()

    def test_layers_place_a_node_below_all_its_prerequisites(self):
        v = view()
        depth = v.layers()
        for edge in v.deps.ordering_edges():
            self.assertGreater(depth[edge.target], depth[edge.source] - 1)


class TestMultipleParents(unittest.TestCase):
    def test_canonical_path_is_one_path_and_is_deterministic(self):
        v = view()
        path = v.canonical_path("D-PDF")
        self.assertEqual(path[0], "D-R0")
        self.assertEqual(path[-1], "D-PDF")
        self.assertEqual(path, view().canonical_path("D-PDF"))

    def test_all_prerequisites_is_larger_than_the_canonical_path(self):
        # D-PDF has several parents; a breadcrumb cannot represent them all.
        v = view()
        self.assertEqual(v.all_prerequisites("D-PDF"),
                         ["D-A1", "D-A2", "D-A3", "D-BOOK", "D-R0"])
        self.assertLess(len(v.canonical_path("D-PDF")) - 1,
                        len(v.all_prerequisites("D-PDF")))

    def test_direct_and_transitive_dependents_differ(self):
        v = view()
        self.assertEqual(v.downstream("D-R0"), ["D-A1", "D-BOOK", "D-COL"])
        self.assertIn("D-PDF", v.all_dependents("D-R0"))


class TestChoices(unittest.TestCase):
    def test_unselected_choice_suppresses_every_arm(self):
        v = view({"choice:demo-text": None})
        sequence = v.reading_sequence()
        self.assertNotIn("D-A2", sequence)
        self.assertNotIn("D-A3", sequence)
        self.assertIn("choice:demo-text", sequence)

    def test_selecting_an_arm_linearises_only_that_arm(self):
        v = view({"choice:demo-text": "D-A2"})
        sequence = v.reading_sequence()
        self.assertIn("D-A2", sequence)
        self.assertNotIn("D-A3", sequence)

    def test_previous_next_stops_at_an_unresolved_choice(self):
        v = view({"choice:demo-text": None})
        self.assertEqual(v.prev_next("D-A2"), (None, None))
        previous, _ = v.prev_next("D-PDF")
        self.assertEqual(previous, "choice:demo-text")

    def test_branches_expose_what_each_arm_unlocks(self):
        branches = view().branches_for("choice:demo-text")
        self.assertEqual([b.option for b in branches], ["D-A2", "D-A3"])
        self.assertIn("D-PDF", branches[0].reachable)

    def test_choice_lookup_from_an_option(self):
        v = view()
        self.assertEqual(v.choice_for_option("D-A2").id, "choice:demo-text")
        self.assertIsNone(v.choice_for_option("D-R0"))


class TestEdgeSemantics(unittest.TestCase):
    def test_non_ordering_edges_do_not_create_prerequisites(self):
        v = view()
        # D-S1 validates D-A2, but validation is not a reading prerequisite.
        self.assertNotIn("D-S1", v.all_prerequisites("D-A2"))

    def test_every_edge_type_has_a_distinguishable_style(self):
        from bibgraph.graph import EDGE_STYLE

        self.assertEqual(set(EDGE_STYLE), set(model.EDGE_TYPES))
        dashes = [s["dash"] for s in EDGE_STYLE.values()]
        colors = [s["color"] for s in EDGE_STYLE.values()]
        self.assertEqual(len(set(dashes)), len(dashes), "dash patterns must be unique")
        self.assertEqual(len(set(colors)), len(colors), "colours must be unique")


class TestLayout(unittest.TestCase):
    def test_layout_is_byte_for_byte_stable(self):
        from bibgraph import util

        self.assertEqual(util.canonical_json(view().layout()),
                         util.canonical_json(view().layout()))

    def test_every_node_receives_a_position(self):
        v = view()
        self.assertEqual(set(v.layout()["positions"]), set(v.nodes))

    def test_adjacency_text_covers_every_node(self):
        v = view()
        self.assertEqual({r["node"] for r in v.adjacency_text()}, set(v.nodes))
