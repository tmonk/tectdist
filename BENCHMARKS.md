# Benchmarks

Performance is measured by a [pytest-benchmark](https://pytest-benchmark.readthedocs.io/)
suite under the uv-managed dev environment.  The numbers below compare the
pre-optimisation baseline with the optimised tree (lazy
imports, lazy proxy globs, deflated zipapp), both measured back-to-back on
the same machine, same interpreter (uv-managed CPython 3.12), same flags.

```sh
uv sync
uv run pytest benchmarks/ --benchmark-only --benchmark-disable-gc \
    --benchmark-json=benchmarks/baseline.json   # before
uv run pytest benchmarks/ --benchmark-only --benchmark-disable-gc \
    --benchmark-json=benchmarks/after.json      # after
```

The `benchmarks/*.json` snapshots are generated locally (gitignored) —
regenerate both together when re-measuring.

## Methodology

- **What is timed:** wall time of the full operation via
  `time.perf_counter()` — a complete `subprocess.run()` for anything that
  spawns the farm, so interpreter startup, imports, dispatch, translation
  and engine spawn are all included.  In-process cases (translate, proxy
  lookup, kpsewhich parse+search) time the function directly.
- **Robustness:** each case runs 1 warmup + N samples (default 15; heavy
  e2e cases 3; the battery 2; override with `TECTDIST_BENCH_SAMPLES=N`).
  Reported stats are the **median, p50 and p95** of the raw samples, which
  stay meaningful under system load.  The pytest-benchmark bookkeeping call
  is bounded via `pedantic(rounds=…)`.
- **Interpreter:** subprocesses resolve `python3` from the `uv run` PATH
  (the uv-managed CPython 3.12).  On a stock system `python3` (e.g. 3.14)
  absolute numbers are higher, but the *relative* deltas below hold.
- **Engine:** the e2e cases use the real Tectonic engine with a warmed
  bundle cache.  They are engine-dominated: their wall time tracks machine
  load far more than the shim (observed compile range across runs:
  187–1254 ms for the same code).  Treat their Δ% as noise, not signal.

## Results (paired run, 2026-08-07, uv-managed CPython 3.12)

Median wall time per operation, milliseconds (lower is better).

| case | before med | p50 | p95 | after med | p50 | p95 | Δ |
|---|---|---|---|---|---|---|---|
| shim/startup warm: `tectdist --version` | 24.5 | 24.5 | 25.8 | 15.0 | 15.0 | 15.8 | **−38.9%** |
| shim/startup artifact: `dist/tectdist --version` | 43.1 | 43.1 | 45.5 | 18.6 | 18.6 | 21.3 | **−56.8%** |
| shim/startup latexmk: `--version` | 32.8 | 32.8 | 40.2 | 23.9 | 23.9 | 25.9 | **−27.1%** |
| shim/startup stub: `mktexlsr` | 41.6 | 41.6 | 53.5 | 22.3 | 22.3 | 23.1 | **−46.3%** |
| shim/startup kpsewhich: `--version` | 28.0 | 28.0 | 30.3 | 23.4 | 23.4 | 24.6 | **−16.3%** |
| shim/startup cold (post-sync): `tectdist --version` | 97.2 | 97.2 | 103.8 | 70.7 | 70.7 | 73.1 | **−27.3%** |
| shim/translation + spawn: pdflatex web2c flags (fake engine) | 44.8 | 44.8 | 55.8 | 40.4 | 40.4 | 43.5 | **−9.9%** |
| shim/translate in-process (CPU only) | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | −11.1% |
| shim/proxy lookup in-process (candidates+globs) | 1.19 | 1.19 | 1.31 | 1.01 | 1.01 | 1.12 | **−14.7%** |
| shim/proxy invocation: `pdfinfo -v` (real poppler) | 40.4 | 40.4 | 45.4 | 32.9 | 32.9 | 34.4 | **−18.6%** |
| shim/kpsewhich subprocess: file lookup | 24.0 | 24.0 | 25.8 | 23.2 | 23.2 | 24.4 | −3.1% |
| shim/kpsewhich in-process (CPU only) | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | 0.01 | +0.0% |
| e2e/compile: `pdflatex tiny.tex` (real tectonic) | 376.0 | 376.0 | 429.0 | 187.7 | 187.7 | 189.2 | noise* |
| e2e/latexmk: driver + compile (real tectonic) | 414.0 | 414.0 | 425.1 | 203.3 | 203.3 | 208.7 | noise* |
| e2e/battery: full acceptance battery (272 checks) | 12057.0 | 12057.0 | 12205.8 | 5550.1 | 5550.1 | 5631.0 | noise* |

\* engine-dominated: the machine was simply lighter during the “after” run
(see methodology).  In the first paired run (heavier load) the same e2e cases
swung the other way (+1.5%…+151%) with the same code; the shim cases improved
in *every* paired run.

## What changed

- **Lazy imports** (`src/tectdist/dispatcher.py`): only `os`, `sys`, `flags`
  and `version` import eagerly.  `subprocess` (~5 ms), `shutil` (~1.5 ms),
  `tools` and `latexmk` are imported on the dispatch paths that need them, so
  every pure-shim invocation (`--version`, stubs, help) skips them.  This is
  the bulk of the startup wins (−39% warm, −57% artifact, −46% stub).
- **Lazy proxy globs** (`src/tectdist/tools.py`): `run_proxy` checks the
  fixed locations first and only evaluates the `/opt/*/bin` globs on a miss
  (previously the globs ran eagerly on every call).  Proxy lookup −15%,
  proxy invocation −19%.
- **Deflated zipapp** (`build.py`): the artifact is written with
  `ZIP_DEFLATED` instead of stored, shrinking `dist/tectdist` from
  46.8 KiB to 14.0 KiB and speeding up cold reads (layout, shebang and
  behaviour unchanged).

## Verification

- Acceptance battery stays green before and after: **272/0/0** (`--jobs 4`),
  also `--mock-only` 223/0/49.
- `dist/tectdist` import audit (stdlib-only) passes: `uv run python
  tests/check_purity.py`.
- `py_compile` clean on CPython 3.12 (dev) and 3.9 (floor).
- No behavioural change: the mock tier asserts exit codes *and* exact engine
  argv — all green.
