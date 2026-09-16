"""Graph algorithms: the curated dependency DAG first, analysis graphs later.

A DAG has no unique breadcrumb, so this module deliberately exposes two
different things: one deterministic canonical path, and the complete set of
prerequisites. Nothing here invents an answer where the data has a genuine
branch.
"""

from __future__ import annotations

import dataclasses
from collections import deque

from .model import Dependencies, Edge, Node

# Rendering hints. Shape and stroke carry the meaning as well as colour, so the
# diagram stays readable without colour perception.
EDGE_STYLE = {
    "prerequisite": {"dash": None, "width": 2.0, "arrow": "solid", "color": "#1f4e79"},
    "backup":       {"dash": "6 3", "width": 1.6, "arrow": "open", "color": "#8a5a00"},
    "validates":    {"dash": "2 3", "width": 1.6, "arrow": "diamond", "color": "#2d6a2d"},
    "conditional":  {"dash": "8 3 2 3", "width": 1.6, "arrow": "open", "color": "#6a2d6a"},
    "orientation":  {"dash": "1 4", "width": 1.4, "arrow": "open", "color": "#555555"},
    "historical":   {"dash": "10 4", "width": 1.4, "arrow": "open", "color": "#7a2d2d"},
}


@dataclasses.dataclass
class Branch:
    """One arm of an unresolved choice."""

    option: str
    reachable: list[str]


class DagView:
    """Read-only navigation over the dependency DAG under a reading profile."""

    def __init__(self, deps: Dependencies, profile: dict[str, str | None] | None = None):
        self.deps = deps
        self.profile = dict(profile or {})
        self.nodes: dict[str, Node] = {n.id: n for n in deps.nodes}
        self.edges: list[Edge] = list(deps.edges)
        self._forward: dict[str, list[Edge]] = {n: [] for n in self.nodes}
        self._reverse: dict[str, list[Edge]] = {n: [] for n in self.nodes}
        for edge in self.edges:
            if edge.source in self._forward and edge.target in self._reverse:
                self._forward[edge.source].append(edge)
                self._reverse[edge.target].append(edge)
        for bucket in (self._forward, self._reverse):
            for key in bucket:
                bucket[key].sort(key=lambda e: (e.type, e.target, e.source))

    # -- adjacency ---------------------------------------------------------

    def outgoing(self, node: str, ordering_only: bool = False) -> list[Edge]:
        edges = self._forward.get(node, [])
        return [e for e in edges if not ordering_only or self._is_ordering(e)]

    def incoming(self, node: str, ordering_only: bool = False) -> list[Edge]:
        edges = self._reverse.get(node, [])
        return [e for e in edges if not ordering_only or self._is_ordering(e)]

    @staticmethod
    def _is_ordering(edge: Edge) -> bool:
        from .model import ORDERING_EDGE_TYPES

        return edge.type in ORDERING_EDGE_TYPES

    def upstream(self, node: str) -> list[str]:
        """Direct prerequisites."""
        return sorted({e.source for e in self.incoming(node, ordering_only=True)})

    def downstream(self, node: str) -> list[str]:
        """Direct dependents."""
        return sorted({e.target for e in self.outgoing(node, ordering_only=True)})

    def all_prerequisites(self, node: str) -> list[str]:
        return sorted(self._closure(node, self._reverse) - {node})

    def all_dependents(self, node: str) -> list[str]:
        return sorted(self._closure(node, self._forward) - {node})

    def _closure(self, start: str, adjacency: dict[str, list[Edge]]) -> set[str]:
        seen = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for edge in adjacency.get(current, []):
                if not self._is_ordering(edge):
                    continue
                nxt = edge.source if adjacency is self._reverse else edge.target
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

    # -- order and layering ------------------------------------------------

    def topological_order(self) -> list[str]:
        """Kahn's algorithm with a lexicographic ready set, so it is stable."""
        indegree = {n: 0 for n in self.nodes}
        for edge in self.edges:
            if self._is_ordering(edge) and edge.target in indegree:
                indegree[edge.target] += 1
        ready = sorted(n for n, d in indegree.items() if d == 0)
        order: list[str] = []
        while ready:
            current = ready.pop(0)
            order.append(current)
            for edge in self.outgoing(current, ordering_only=True):
                indegree[edge.target] -= 1
                if indegree[edge.target] == 0:
                    ready.append(edge.target)
                    ready.sort()
        if len(order) != len(self.nodes):
            missing = sorted(set(self.nodes) - set(order))
            raise ValueError(f"dependency graph is cyclic; unordered nodes: {missing}")
        return order

    def layers(self) -> dict[str, int]:
        """Longest-path depth: a node sits below every one of its prerequisites."""
        depth = {n: 0 for n in self.nodes}
        for node in self.topological_order():
            for edge in self.outgoing(node, ordering_only=True):
                depth[edge.target] = max(depth[edge.target], depth[node] + 1)
        # A choice sits with its shallowest option so it is met before either arm.
        for node in self.nodes.values():
            if node.kind == "choice" and node.options:
                depth[node.id] = min(depth.get(o, 0) for o in node.options)
        return depth

    def canonical_path(self, node: str) -> list[str]:
        """One deterministic path from a root to `node`.

        A DAG node can have many parents, so this is a display convenience, not
        the truth. `all_prerequisites` is the truth, and the work page shows it
        separately.
        """
        depth = self.layers()
        path = [node]
        current = node
        seen = {node}
        while True:
            parents = self.upstream(current)
            if not parents:
                break
            # Deepest parent first, then alphabetical: stable across runs.
            parents = [p for p in parents if p not in seen]
            if not parents:
                break
            current = sorted(parents, key=lambda p: (-depth.get(p, 0), p))[0]
            seen.add(current)
            path.append(current)
        return list(reversed(path))

    # -- choices and reading order ----------------------------------------

    def choices(self) -> list[Node]:
        return sorted((n for n in self.nodes.values() if n.kind == "choice"),
                      key=lambda n: n.id)

    def selection(self, choice_id: str) -> str | None:
        return self.profile.get(choice_id)

    def suppressed_options(self) -> set[str]:
        """Options excluded from the linear reading order.

        With a selection, the rejected arms drop out. With no selection,
        *every* arm drops out and the choice node itself stands in their place:
        the navigator stops there and offers the branches rather than picking
        one.
        """
        suppressed: set[str] = set()
        for choice in self.choices():
            selected = self.selection(choice.id)
            for option in choice.options:
                if option != selected:
                    suppressed.add(option)
        return suppressed

    def reading_sequence(self) -> list[str]:
        """Stable linear order for Previous/Next under the current profile."""
        suppressed = self.suppressed_options()
        depth = self.layers()
        order = self.topological_order()
        position = {n: i for i, n in enumerate(order)}
        visible = [n for n in order if n not in suppressed]
        return sorted(visible, key=lambda n: (depth.get(n, 0), position[n]))

    def prev_next(self, node: str) -> tuple[str | None, str | None]:
        sequence = self.reading_sequence()
        if node not in sequence:
            return (None, None)
        index = sequence.index(node)
        return (sequence[index - 1] if index > 0 else None,
                sequence[index + 1] if index + 1 < len(sequence) else None)

    def branches_for(self, choice_id: str) -> list[Branch]:
        node = self.nodes[choice_id]
        return [Branch(option=o, reachable=self.all_dependents(o)) for o in node.options]

    def choice_for_option(self, node_id: str) -> Node | None:
        for choice in self.choices():
            if node_id in choice.options:
                return choice
        return None

    # -- layout ------------------------------------------------------------

    def layout(self, column_width: int = 210, row_height: int = 78,
               margin: int = 28) -> dict:
        """Deterministic coordinates. Same inputs give byte-identical output."""
        depth = self.layers()
        buckets: dict[int, list[str]] = {}
        for node in sorted(self.nodes):
            buckets.setdefault(depth.get(node, 0), []).append(node)

        positions: dict[str, tuple[int, int]] = {}
        for layer in sorted(buckets):
            for index, node in enumerate(buckets[layer]):
                positions[node] = (margin + index * column_width,
                                   margin + layer * row_height)
        width = margin * 2 + max((len(v) for v in buckets.values()), default=1) * column_width
        height = margin * 2 + (max(buckets) + 1 if buckets else 1) * row_height
        return {
            "positions": {k: {"x": v[0], "y": v[1]} for k, v in sorted(positions.items())},
            "layers": {str(k): v for k, v in sorted(buckets.items())},
            "width": width,
            "height": height,
        }

    def adjacency_text(self) -> list[dict]:
        """Textual adjacency list: the accessible equivalent of the diagram."""
        rows = []
        for node in sorted(self.nodes):
            rows.append({
                "node": node,
                "kind": self.nodes[node].kind,
                "prerequisites": [
                    {"node": e.source, "type": e.type} for e in self.incoming(node)],
                "dependents": [
                    {"node": e.target, "type": e.type} for e in self.outgoing(node)],
            })
        return rows
