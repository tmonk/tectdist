"""End-to-end benchmarks with the REAL Tectonic engine (warmed bundle cache):
a plain compile, the latexmk driver, and the whole acceptance battery.
These are dominated by the engine — the shim's share is the interesting part.

Skipped (not failed) when no tectonic engine is available, like the battery's
[real] tier.  First-ever runs may download Tectonic's bundle; warm it first
with a manual `bin/pdflatex -interaction=nonstopmode` on any .tex file.
"""

import os
import subprocess
import sys

import pytest

from helpers import BIN, ROOT, bench_case, find_engine, run_cmd, samples_for

pytestmark = pytest.mark.skipif(
    not find_engine(), reason="tectonic engine not available")


def test_e2e_compile(benchmark, scratch, have_engine):
    """bin/pdflatex tiny.tex — full real compile through the shim."""

    def once():
        r = run_cmd([str(BIN / "pdflatex"), "-interaction=nonstopmode",
                     "tiny.tex"], cwd=scratch, timeout=60)
        assert r.returncode == 0, r.stdout.decode(errors="replace")

    bench_case(benchmark, once, samples_for(heavy=True), rounds=2,
               label="e2e/compile: pdflatex tiny.tex (real tectonic)")


def test_e2e_latexmk(benchmark, scratch, have_engine):
    """bin/latexmk -pdf -outdir=out -jobname=bench tiny.tex — driver flow."""

    def once():
        r = run_cmd([str(BIN / "latexmk"), "-pdf", "-outdir=out",
                     "-jobname=bench", "tiny.tex"], cwd=scratch, timeout=60)
        assert r.returncode == 0, r.stdout.decode(errors="replace")

    bench_case(benchmark, once, samples_for(heavy=True), rounds=2,
               label="e2e/latexmk: driver + compile (real tectonic)")


def test_e2e_battery_total(benchmark, scratch, have_engine):
    """Whole acceptance battery wall time (the equivalence gate)."""

    def once():
        r = run_cmd(["python3", str(ROOT / "tests" / "battery.py"),
                     "--jobs", "4"], timeout=600)
        assert r.returncode == 0, r.stdout.decode(errors="replace")

    bench_case(benchmark, once, samples_for("battery"), rounds=1,
               label="e2e/battery: full acceptance battery (272 checks)")
