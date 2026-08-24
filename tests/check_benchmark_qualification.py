#!/usr/bin/env python3
"""Ensure release-grade benchmark mode cannot silently emit weak provenance."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
environment = os.environ.copy()
environment.pop("TECTDIST_BUNDLE_ID", None)
environment.pop("TECTDIST_FORMAT_CACHE_ID", None)
result = subprocess.run(
    [sys.executable, "-m", "benchmarks.runner.cli", "--candidate", "/bin/true",
     "--qualification", "--warmups", "5", "--trials", "30", "--output", "/tmp/unused.json"],
    cwd=ROOT, env=environment, capture_output=True, text=True)
assert result.returncode != 0
assert "TECTDIST_BUNDLE_SOURCE" in result.stderr
assert "TECTDIST_BUNDLE_MANIFEST_SHA256" in result.stderr

provenance = environment.copy()
provenance.update({
    "TECTDIST_BUNDLE_SOURCE": "fixture://bundle",
    "TECTDIST_BUNDLE_ID": "bundle-1",
    "TECTDIST_BUNDLE_MANIFEST_SHA256": "abc123",
    "TECTDIST_FORMAT_CACHE_ID": "format-1",
    "TECTDIST_TEXLIVE_SOURCE": "fixture://texlive",
    "TECTDIST_TEXLIVE_ID": "texlive-1",
    "TECTDIST_TEXLIVE_MANIFEST_SHA256": "def456",
    "TECTDIST_TEXLIVE_FORMAT_ID": "pdflatex-format-1",
    "TECTDIST_BENCH_DIRECT_TECTONIC": "/bin/true",
})
incomplete = subprocess.run(
    [sys.executable, "-m", "benchmarks.runner.cli", "--candidate", "/bin/true",
     "--qualification", "--warmups", "5", "--trials", "30", "--output", "/tmp/unused.json"],
    cwd=ROOT, env=provenance, capture_output=True, text=True)
assert incomplete.returncode != 0
assert "texlive-latexmk" in incomplete.stderr

too_few_expensive = subprocess.run(
    [sys.executable, "-m", "benchmarks.runner.cli", "--candidate", "/bin/true",
     "--qualification", "--expensive-case", "--warmups", "1", "--trials", "14",
     "--output", "/tmp/unused.json"], cwd=ROOT, env=provenance,
    capture_output=True, text=True)
assert too_few_expensive.returncode != 0
assert "15 paired trials" in too_few_expensive.stderr

cold = subprocess.run(
    [sys.executable, "-m", "benchmarks.runner.cli", "--candidate", "/bin/true",
     "--scenario", "cold-empty-cache", "--output", "/tmp/unused.json"],
    cwd=ROOT, env=environment, capture_output=True, text=True)
assert cold.returncode != 0
assert "--cold-source" in cold.stderr

from benchmarks.runner.cli import repository_provenance
commit, dirty = repository_provenance()
assert len(commit) >= 7
assert isinstance(dirty, bool)
print("check_benchmark_qualification: OK")
