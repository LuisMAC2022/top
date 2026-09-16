"""Shared test helpers: temporary workspaces built from the demo fixture."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from bibgraph.util import Workspace

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DEMO = FIXTURES / "demo"


class WorkspaceCase(unittest.TestCase):
    """A test case with an isolated project root seeded from a fixture config."""

    fixture = DEMO

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="bibgraph-test-")
        self.root = Path(self._tmp)
        shutil.copytree(self.fixture / "config", self.root / "config")
        self.ws = Workspace.from_root(self.root)
        self.ws.ensure()
        self.addCleanup(shutil.rmtree, self._tmp, True)

    def run_cli(self, *argv: str) -> int:
        from bibgraph.cli import main

        return main(["--root", str(self.root), *argv])
