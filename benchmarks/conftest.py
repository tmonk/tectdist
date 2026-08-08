"""Shared fixtures for the tectdist benchmark suite."""

import pathlib
import subprocess
import sys

import pytest

from helpers import BIN, FAKE_ENGINE, ROOT, TINY, find_engine, run_cmd


@pytest.fixture(scope="session")
def artifact(tmp_path_factory):
    """Build dist/tectdist once per session (into a temp dir)."""
    dest = tmp_path_factory.mktemp("artifact") / "tectdist"
    r = run_cmd([sys.executable, str(ROOT / "build.py"), "-o", str(dest)])
    assert r.returncode == 0, r.stderr.decode(errors="replace")
    return dest


@pytest.fixture(scope="session")
def fake_engine(tmp_path_factory):
    """A recording-free stand-in engine: exits 0 immediately."""
    p = tmp_path_factory.mktemp("fakeeng") / "fake-engine.py"
    p.write_text(FAKE_ENGINE)
    p.chmod(0o755)
    return p


@pytest.fixture
def scratch(tmp_path):
    """A scratch dir with a tiny.tex (and a styles/ dir for kpsewhich)."""
    (tmp_path / "tiny.tex").write_text(TINY)
    (tmp_path / "main.tex").write_text(TINY)
    (tmp_path / "styles").mkdir()
    (tmp_path / "styles" / "mystyle.sty").write_text(
        "\\newcommand{\\mystuff}{styled}\n")
    return tmp_path


@pytest.fixture(scope="session")
def have_engine():
    return bool(find_engine())
