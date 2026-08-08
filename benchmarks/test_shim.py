"""Shim-overhead benchmarks: interpreter startup, dispatch, flag translation,
proxy resolution and kpsewhich lookup — measured WITHOUT a real engine
(version/help paths, stubs, the recording-free fake engine for translation).
These are the numbers we control directly and therefore optimise hardest.
"""

import glob
import os
import shutil
import subprocess
import sys

import pytest

from helpers import (BIN, ROOT, SRC, bench_case, engine_env, run_cmd,
                     samples_for)


def _run(prog, *args, cwd=None, env=None):
    return lambda: run_cmd([str(BIN / prog), *args], cwd=cwd, env=env)


# ---------------------------------------------------------------------------
# startup: pure shim, no engine involved
# ---------------------------------------------------------------------------

def test_startup_tectdist_version_warm(benchmark):
    """bin/tectdist --version — hot page cache (the common case)."""
    bench_case(benchmark, _run("tectdist", "--version"),
               samples_for(), "shim/startup warm: tectdist --version")


def test_startup_tectdist_version_cold(benchmark):
    """bin/tectdist --version right after sync(8) — cold-ish page cache."""
    sync = shutil.which("sync") or "/sbin/sync"

    def once():
        run_cmd([sync])
        run_cmd([str(BIN / "tectdist"), "--version"])

    bench_case(benchmark, once, samples_for(),
               "shim/startup cold (post-sync): tectdist --version")


def test_startup_artifact_version(benchmark, artifact):
    """The built zipapp (dist/tectdist) --version — import-from-zip overhead."""
    bench_case(benchmark, lambda: run_cmd([str(artifact), "--version"]),
               samples_for(), "shim/startup artifact: dist/tectdist --version")


def test_startup_latexmk_version(benchmark):
    """bin/latexmk --version — the heaviest import path (driver module)."""
    bench_case(benchmark, _run("latexmk", "--version"),
               samples_for(), "shim/startup latexmk: --version")


def test_startup_stub(benchmark):
    """bin/mktexlsr — silent stub dispatch, no output, no engine."""
    bench_case(benchmark, _run("mktexlsr"),
               samples_for(), "shim/startup stub: mktexlsr")


def test_startup_kpsewhich_version(benchmark):
    """bin/kpsewhich --version — tools module path."""
    bench_case(benchmark, _run("kpsewhich", "--version"),
               samples_for(), "shim/startup kpsewhich: --version")


# ---------------------------------------------------------------------------
# flag translation
# ---------------------------------------------------------------------------

def test_flag_translation_mock_engine(benchmark, fake_engine, scratch):
    """Full dispatch: translate a realistic web2c flag set and spawn the
    (fake) engine — shim startup + translation + spawn, no TeX work."""
    args = ["-interaction=nonstopmode", "-synctex=1", "-shell-escape",
            "-output-directory=out", "-jobname=bench", "main.tex"]
    bench_case(benchmark,
               lambda: run_cmd([str(BIN / "pdflatex"), *args],
                               cwd=scratch, env=engine_env(fake_engine)),
               samples_for(),
               "shim/translation + spawn: pdflatex web2c flags (fake engine)")


def test_translate_inprocess(benchmark, scratch):
    """translate() alone (no subprocess, no startup) — pure CPU cost."""
    import tectdist.dispatcher as d
    args = ["-interaction=nonstopmode", "-synctex=1", "-shell-escape",
            "-output-directory=out", "-jobname=bench", "main.tex"]
    bench_case(benchmark, lambda: d.translate(args, "pdflatex"),
               samples_for(), "shim/translate in-process (CPU only)")


# ---------------------------------------------------------------------------
# proxy resolution (poppler/qpdf passthrough)
# ---------------------------------------------------------------------------

def _proxy_candidates(prog):
    """Mirror of tools.run_proxy's candidate search (incl. the opt globs)."""
    cands = [f"/opt/homebrew/bin/{prog}", f"/usr/local/bin/{prog}",
             f"/usr/bin/{prog}", shutil.which(prog) or ""]
    cands += sorted(glob.glob(f"/opt/homebrew/opt/*/bin/{prog}"))
    cands += sorted(glob.glob(f"/usr/local/opt/*/bin/{prog}"))
    return cands


def test_proxy_resolution_inprocess(benchmark):
    """The candidate + glob search run_proxy performs on every call."""
    bench_case(benchmark, lambda: _proxy_candidates("pdfinfo"),
               samples_for(), "shim/proxy lookup in-process (candidates+globs)")


@pytest.mark.skipif(not shutil.which("pdfinfo"), reason="pdfinfo not installed")
def test_proxy_invocation_subprocess(benchmark, scratch):
    """bin/pdfinfo -v — proxy dispatch that execs the real poppler binary."""
    bench_case(benchmark, _run("pdfinfo", "-v"),
               samples_for(), "shim/proxy invocation: pdfinfo -v (real poppler)")


# ---------------------------------------------------------------------------
# kpsewhich lookup
# ---------------------------------------------------------------------------

def test_kpsewhich_subprocess(benchmark, scratch):
    """bin/kpsewhich mystyle.sty with TEXINPUTS — parse + search + print."""
    env = os.environ.copy()
    env["TEXINPUTS"] = str(scratch / "styles")
    bench_case(benchmark,
               lambda: run_cmd([str(BIN / "kpsewhich"), "mystyle.sty"],
                               cwd=scratch, env=env),
               samples_for(), "shim/kpsewhich subprocess: file lookup")


def test_kpsewhich_inprocess(benchmark, scratch):
    """kpsewhich_main() alone — parse + search, no subprocess overhead."""
    import tectdist.tools as tools
    os.environ["TEXINPUTS"] = str(scratch / "styles")
    bench_case(benchmark, lambda: tools.kpsewhich_main(["mystyle.sty"]),
               samples_for(), "shim/kpsewhich in-process (CPU only)")
