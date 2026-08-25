#!/usr/bin/env python3
"""R-milestone release gate: one command, every verification stage.

Chains the full BT100/X10 verification surface and emits a consolidated
verdict. Stages:

  1. workspace-tests      cargo test --locked --workspace
  2. differential         tests/differential.py against the native build
  3. bib-differential     tests/bib_differential.py
  4. bt100-report-gate    basictex_report.py must emit gate_pass=true
  5. doc-equivalence      13/13 manifest documents vs pinned reference
  6. fail-equivalence     directional equivalence on reference-blocked set
  7. x10-e-edit           supervisor-path edit-scenario speedups
                          (>=10x required on every declared scenario;
                           expected FAILING until page checkpoints land)
  8. x10-c-warm-clean     runtime-warm project-clean aggregate
                          (placeholder: pending engine-side tokenised
                           caches; reported as pending, never silently
                           skipped)

Exit 0 iff every stage passes AND no stage is pending.
Writes reference/basictex-2026/release-gate.json (+ .md).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "reference" / "basictex-2026"
IMAGE = ROOT / ("reference/basictex-2026/installer/expanded/"
                "BasicTeX-2026-Start.pkg/Payload/usr/local/texlive/2026basic")


def ensure_pkg_config_path():
    """Build stages need the brew keg-only pkgconfig dirs; CI exports this,
    local runs may not. Idempotent."""
    if os.environ.get("PKG_CONFIG_PATH"):
        return
    prefixes = ["icu4c@78", "freetype", "harfbuzz", "graphite2", "libpng"]
    parts = []
    for prefix in prefixes:
        brew = subprocess.run(["brew", "--prefix", prefix],
                              capture_output=True, text=True)
        if brew.returncode == 0:
            parts.append(f"{brew.stdout.strip()}/lib/pkgconfig")
    if parts:
        os.environ["PKG_CONFIG_PATH"] = ":".join(parts)


def sh(cmd: list[str], timeout: int | None = None):
    return subprocess.run(cmd, cwd=ROOT, capture_output=True,
                          text=True, timeout=timeout)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--skip-build", action="store_true",
                    help="reuse target/release binaries")
    ap.add_argument("--doc-equivalence-pairs", type=int, default=None,
                    help="unused; kept for interface stability")
    ap.add_argument("--out", type=Path, default=REF / "release-gate.json")
    args = ap.parse_args(argv)
    ensure_pkg_config_path()

    stages = []

    def record(name: str, status: str, detail: str, seconds: float):
        stages.append({"stage": name, "status": status,
                       "detail": detail, "seconds": round(seconds, 1)})
        print(f"[{status:>7}] {name}: {detail}")

    # 1. workspace tests --------------------------------------------------
    t0 = time.time()
    env_cmd = ["cargo", "test", "--locked", "--workspace"]
    result = sh(env_cmd, timeout=3600)
    passed = sum(int(token) for token in __import__("re").findall(
        r"(\d+) passed", result.stdout))
    record("workspace-tests",
           "pass" if result.returncode == 0 else "fail",
           f"returncode={result.returncode}, {passed} tests passed",
           time.time() - t0)

    # 2/3. native build + differentials -----------------------------------
    t0 = time.time()
    native = Path("/tmp/td-release-gate")
    build = sh(["python3", "build.py", "--native", "-o", str(native)],
               timeout=1800)
    t1 = time.time()
    if build.returncode == 0:
        env = {**os.environ, "TECTDIST_NATIVE": str(native)}
        diff = subprocess.run(
            [sys.executable, "tests/differential.py"], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=1200)
        bib = subprocess.run(
            [sys.executable, "tests/bib_differential.py"], cwd=ROOT, env=env,
            capture_output=True, text=True, timeout=1200)
        record("differential",
               "pass" if diff.returncode == 0 else "fail",
               (diff.stdout.strip().splitlines() or [""])[-1],
               t1 - t0)
        record("bib-differential",
               "pass" if bib.returncode == 0 else "fail",
               (bib.stdout.strip().splitlines() or [""])[-1],
               time.time() - t1)
    else:
        record("differential", "fail",
               f"native build failed: rc={build.returncode}", time.time() - t0)

    # 4. BT100 report gate -----------------------------------------------
    t0 = time.time()
    report = sh(["python3", "scripts/basictex_report.py"], timeout=600)
    try:
        gate = json.loads((REF / "bt100-report.json").read_text())
        gate_pass = bool(gate.get("gate_pass"))
        summary = gate.get("summary", {})
        detail = (f"{summary.get('pass')} pass / {summary.get('fail')} fail / "
                  f"{summary.get('reference_blocked')} reference-blocked")
    except Exception as error:
        gate_pass, detail = False, f"unreadable report: {error}"
    record("bt100-report-gate",
           "pass" if gate_pass and report.returncode == 0 else "fail",
           detail, time.time() - t0)

    # 5. document equivalence --------------------------------------------
    t0 = time.time()
    docs = ["multifile", "paper", "tiny", "bibtex", "index", "tikz",
            "shell-escape", "references", "graphics", "thesis",
            "unicode-fonts", "beamer", "biblatex", "glossary"]
    doc = sh(["python3", "scripts/basictex_doc_equivalence.py",
              "--reference", str(IMAGE),
              "--candidate", str(ROOT / "target/release/tectdist"),
              "--documents", *docs], timeout=2400)
    record("doc-equivalence",
           "pass" if doc.returncode == 0 else "fail",
           (doc.stdout.strip().splitlines() or [""])[-1], time.time() - t0)

    # 6. failure equivalence ----------------------------------------------
    t0 = time.time()
    fail_eq = sh(["python3", "scripts/basictex_fail_equivalence.py",
                  "--reference", str(IMAGE)], timeout=2400)
    record("fail-equivalence",
           "pass" if fail_eq.returncode == 0 else "fail",
           (fail_eq.stdout.strip().splitlines() or [""])[-1], time.time() - t0)

    # 7. X10-E edit scenarios ---------------------------------------------
    t0 = time.time()
    x10e = sh(["python3", "scripts/basictex_x2_edit_scenarios.py",
               "--out", str(REF / "x2-edit-scenarios.json")], timeout=1200)
    try:
        data = json.loads((REF / "x2-edit-scenarios.json").read_text())
        speedups = {
            "body-edit": data["speedup_body_edit_vs_stock"],
            "unchanged": data["speedup_unchanged_vs_stock"],
        }
        # Declared manifest scenarios measured alongside (structural
        # section additions reuse the format like body edits).
        scenarios = data.get("scenarios", {})
        if "structural-edit-format-reused" in scenarios:
            speedups["structural-edit"] = round(
                scenarios["stock-one-shot"]
                / max(scenarios["structural-edit-format-reused"], 1), 3)
        meets = all(v >= 10.0 for v in speedups.values()) and \
            x10e.returncode == 0
        detail = ", ".join(f"{k} {v}x" for k, v in speedups.items())
        status = "pass" if meets else "fail"
        if not meets:
            detail += (" — below 10x; requires engine-side page checkpoints "
                       "(documented)")
    except Exception as error:
        status, detail = "fail", f"unreadable results: {error}"
    record("x10-e-edit", status, detail, time.time() - t0)

    # 8. X10-C runtime-warm clean -----------------------------------------
    record("x10-c-warm-clean", "pending",
           "tokenised caches require engine-side work (X6); no "
           "implementation exists to measure yet", 0.0)

    overall = (all(s["status"] == "pass" for s in stages)
               and not any(s["status"] == "pending" for s in stages))

    out = {
        "schema_version": 1,
        "overall": "PASS" if overall else "FAIL",
        "stages": stages,
    }
    args.out.write_text(json.dumps(out, indent=2) + "\n")
    md = ["# Release gate (R milestone)", "",
          f"Overall: **{out['overall']}**", "",
          "| stage | status | detail |", "|---|---|---|"]
    md += [f"| {s['stage']} | {s['status']} | {s['detail']} |"
           for s in stages]
    args.out.with_suffix(".md").write_text("\n".join(md) + "\n")

    failing = [s["stage"] for s in stages if s["status"] != "pass"]
    print(f"\noverall: {out['overall']}; non-passing: "
          f"{', '.join(failing) or 'none'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())


