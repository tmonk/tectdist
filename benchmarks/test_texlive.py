"""Compile time: tectdist (Tectonic) vs real TeX Live/MiKTeX, same document.

The comparison is tectdist's single command against TeX Live's `latexmk`,
not a bare `pdflatex` pass on each side.  A bare pass is not an
apples-to-apples baseline: `paper.tex` (see helpers.PAPER) needs a rerun to
resolve its hyperref outline, so a single raw `pdflatex` leaves TeX Live
with a stale PDF outline while tectdist's single command already reruns
automatically to converge.  `latexmk` is TeX Live's own answer to "give me
a fully-resolved PDF in one command" -- the fair opposite number.

Skipped (not failed) unless both a tectonic engine AND a non-tectdist
`latexmk` are on PATH.  Warm both sides' caches first (a manual
`bin/pdflatex -interaction=nonstopmode` on any `.tex` file for Tectonic's
bundle, one prior `latexmk` run for TeX Live's formats) so neither run pays
a one-time init cost.
"""

import pytest

from helpers import (BIN, bench_case, find_engine, find_texlive_latexmk,
                      run_cmd, samples_for)

TEXLIVE_LATEXMK = find_texlive_latexmk()

pytestmark = pytest.mark.skipif(
    not (find_engine() and TEXLIVE_LATEXMK),
    reason="need both a tectonic engine and a real (non-tectdist) "
           "latexmk on PATH")


def test_compile_tectdist(benchmark, paper_scratch, have_engine):
    """bin/pdflatex paper.tex -- one command, fully-resolved PDF."""

    def once():
        for name in ("paper.pdf", "paper.aux", "paper.out", "paper.log"):
            p = paper_scratch / name
            if p.exists():
                p.unlink()
        r = run_cmd([str(BIN / "pdflatex"), "-interaction=nonstopmode",
                     "paper.tex"], cwd=paper_scratch, timeout=60)
        assert r.returncode == 0, r.stdout.decode(errors="replace")

    bench_case(benchmark, once, samples_for(heavy=True), rounds=2,
               label="texlive-compare/tectdist: pdflatex paper.tex (tectonic)")


def test_compile_texlive_latexmk(benchmark, paper_scratch):
    """TeX Live's own latexmk paper.tex -- its fully-resolved-PDF answer."""

    def once():
        for name in ("paper.pdf", "paper.aux", "paper.out", "paper.log",
                     "paper.fdb_latexmk", "paper.fls"):
            p = paper_scratch / name
            if p.exists():
                p.unlink()
        r = run_cmd([TEXLIVE_LATEXMK, "-pdf", "-interaction=nonstopmode",
                     "paper.tex"], cwd=paper_scratch, timeout=60)
        assert r.returncode == 0, r.stdout.decode(errors="replace")

    bench_case(benchmark, once, samples_for(heavy=True), rounds=2,
               label="texlive-compare/texlive: latexmk paper.tex (real texlive)")
