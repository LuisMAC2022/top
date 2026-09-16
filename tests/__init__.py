"""Test package.

Makes `python -m unittest` work from a clean checkout with the plan's `src/`
layout, which has no packaging step: unittest's default discovery only recurses
into importable packages, and this file puts `src` on the path before any test
module imports bibgraph.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
