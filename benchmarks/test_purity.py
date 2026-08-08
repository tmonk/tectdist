"""The built artifact must stay stdlib-only — the same audit as
tests/check_purity.py, wrapped so the benchmark suite enforces it."""

import subprocess
import sys

from helpers import ROOT


def test_artifact_purity(artifact):
    r = subprocess.run([sys.executable, str(ROOT / "tests" / "check_purity.py"),
                        str(artifact)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
