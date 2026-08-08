"""Shared helpers for the tectdist benchmark suite (pytest + pytest-benchmark).

This toolchain is DEV-ONLY and uv-managed: benchmarks need pytest /
pytest-benchmark, installed via `uv sync` (see pyproject.toml,
[dependency-groups] dev).  The runtime, the installers, tests/battery.py and
tests/check_purity.py remain stdlib-only Python >= 3.9 and run on a stock
python3 with neither uv nor any site-packages.

Measurement model
-----------------
Every case times a run_once() callable with time.perf_counter().  We collect
`samples` raw timings (plus one warmup) and report median / p50 / p95, which
stays meaningful even when the machine is under load; we additionally hand one
representative call to the pytest-benchmark fixture so `--benchmark-only` mode
and `--benchmark-json` work as usual.

Quick runs:    TECTDIST_BENCH_SAMPLES=5 python -m pytest benchmarks/
"""

import os
import pathlib
import statistics
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
BIN = ROOT / "bin"
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

FAKE_ENGINE = "#!/usr/bin/env python3\nimport sys\nsys.exit(0)\n"

TINY = ("\\documentclass{article}\n\\begin{document}\n"
        "Hello \\LaTeX{} world.\n\\end{document}\n")

HEAVY_SAMPLES = 3      # real-engine compile / latexmk cases
BATTERY_SAMPLES = 2    # the whole battery takes ~11 s per run


def samples_for(heavy=False):
    """Sample count; TECTDIST_BENCH_SAMPLES overrides everything."""
    env = os.environ.get("TECTDIST_BENCH_SAMPLES")
    if env:
        return max(1, int(env))
    if heavy == "battery":
        return BATTERY_SAMPLES
    return HEAVY_SAMPLES if heavy else 15


def measure(run_once, samples, warmup=1):
    """Run one warmup + `samples` timed calls; sorted raw ms list returned."""
    for _ in range(warmup):
        run_once()
    dts = []
    for _ in range(samples):
        t0 = time.perf_counter()
        run_once()
        dts.append((time.perf_counter() - t0) * 1000.0)
    dts.sort()
    q = statistics.quantiles(dts, n=100, method="inclusive")
    return statistics.median(dts), q[49], q[94], dts


def bench_case(benchmark, run_once, samples, label, rounds=5):
    """Our sample loop + one representative pytest-benchmark call.

    The raw-sample stats (median_ms / p50_ms / p95_ms) land in
    benchmark.extra_info and are the numbers BENCHMARKS.md reports.
    pedantic() with explicit rounds/iterations keeps pytest-benchmark's
    own loop bounded (its adaptive calibration would otherwise run tens
    of thousands of rounds for fast in-process cases).
    """
    med, p50, p95, _ = measure(run_once, samples)
    benchmark.pedantic(run_once, rounds=rounds, iterations=1, warmup_rounds=0)
    benchmark.extra_info.update(
        case=label, samples=samples, unit="ms",
        median_ms=round(med, 3), p50_ms=round(p50, 3), p95_ms=round(p95, 3))
    return med


def run_cmd(cmd, cwd=None, env=None, timeout=120):
    return subprocess.run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=timeout)


def engine_env(fake_engine):
    env = os.environ.copy()
    env["TECTONIC"] = str(fake_engine)
    return env


def find_engine():
    """Mirror of the dispatcher's engine resolution (TECTONIC -> PATH -> brew)."""
    cand = os.environ.get("TECTONIC", "")
    if not cand:
        which = shutil_which("tectonic")
        cand = which or ""
    if not cand and os.path.isfile("/opt/homebrew/bin/tectonic"):
        cand = "/opt/homebrew/bin/tectonic"
    return cand if cand and os.path.isfile(cand) else ""


def shutil_which(name):
    import shutil
    return shutil.which(name) or ""
