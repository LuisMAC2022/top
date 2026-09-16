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

    def run_cli(self, *argv: str, capture: bool = True) -> int:
        """Invoke the CLI in-process, silencing its output by default."""
        import contextlib
        import io

        from bibgraph.cli import main

        if not capture:
            return main(["--root", str(self.root), *argv])
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(self.stdout), \
                contextlib.redirect_stderr(self.stderr):
            return main(["--root", str(self.root), *argv])
