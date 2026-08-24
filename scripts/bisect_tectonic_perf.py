#!/usr/bin/env python3
"""Automated Tectonic performance bisecting (plan X3.3).

Given a known-good and a known-bad upstream commit, walks the upstream
history, builds tectdist against each candidate revision with a pinned
toolchain, runs tiny / paper / QFT / font-heavy benchmark cases with
correctness gates, and classifies each commit as good, bad, or unbuildable.
At the boundary it emits stage and flamegraph comparison pointers.

Usage:
    python3 scripts/bisect_tectonic_perf.py --good <commit> --bad <commit> \
        [--steps 12] [--output benchmark-results/bisect]

The workspace inputs are backed up and restored; run on a clean tree.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from tectonic_perf_matrix import (  # noqa: E402
    ENGINE_TOML,
    WORKSPACE_LOCK,
    WORKSPACE_TOML,
    evaluate_revision,
    log,
    rewrite_engine_dependency,
    sh,
)


def upstream_commits(good, bad):
    """List commits from good..bad oldest-first using the cargo git checkout."""
    checkouts = Path.home() / ".cargo/git/checkouts"
    candidates = sorted(checkouts.glob("tectonic-*/"))
    if not candidates:
        raise SystemExit("no cargo git checkout of tectonic found")
    checkout = max(candidates.iterdir(), key=lambda p: p.stat().st_mtime)
    result = sh(["git", "rev-list", "--reverse", f"{good}..{bad}"], cwd=checkout)
    return [line for line in result.stdout.splitlines() if line], checkout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--good", required=True, help="known-good upstream commit")
    parser.add_argument("--bad", required=True, help="known-bad upstream commit")
    parser.add_argument("--gate-tiny-ms", type=float, default=150.0)
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--output", default=str(ROOT / "benchmark-results/bisect"))
    ns = parser.parse_args(argv)

    outdir = Path(ns.output)
    outdir.mkdir(parents=True, exist_ok=True)
    commits, checkout = upstream_commits(ns.good, ns.bad)
    if len(commits) > ns.max_steps:
        # Sample evenly to keep wall time bounded while bracketing the fault.
        stride = len(commits) // ns.max_steps + 1
        commits = commits[::stride]

    workspace_original = WORKSPACE_TOML.read_text()
    lock_original = WORKSPACE_LOCK.read_text()
    engine_original = ENGINE_TOML.read_text()

    timeline = []
    try:
        for commit in commits:
            label = commit[:12]
            log(f"evaluating {label}")
            entry = {"commit": commit, "classification": "unbuildable"}
            try:
                rewrite_engine_dependency("rev", commit)
                sh(["cargo", "build", "--release", "-p", "tectdist-cli"])
                binary = ROOT / "target/release/tectdist"
                medians, error = evaluate_revision(binary)
                if medians is None:
                    entry["error"] = (error or "")[:400]
                else:
                    entry["medians_ms"] = medians
                    tiny = medians.get("tiny")
                    entry["classification"] = (
                        "good" if tiny is not None and tiny <= ns.gate_tiny_ms else "bad")
            except RuntimeError as error:
                entry["error"] = str(error)[:400]
            timeline.append(entry)
            log(f"{label}: {entry['classification']}")
            (outdir / "bisect.json").write_text(json.dumps(timeline, indent=2) + "\n")
            if entry["classification"] == "bad":
                break
    finally:
        WORKSPACE_TOML.write_text(workspace_original)
        WORKSPACE_LOCK.write_text(lock_original)
        ENGINE_TOML.write_text(engine_original)
        sh(["cargo", "fetch"], check=False)

    bad_commit = next((e for e in timeline if e["classification"] == "bad"), None)
    summary = ["# Tectonic performance bisect", "",
               f"range: {ns.good[:12]}..{ns.bad[:12]}", ""]
    if bad_commit:
        summary.append(f"first measured bad commit: `{bad_commit['commit']}`")
        summary.append("")
        summary.append("Follow-ups at the boundary:")
        summary.append("- stage comparison: `python -m benchmarks.runner.stage_budget` "
                       "on traced diagnostics from both boundary revisions")
        summary.append("- flamegraphs: `scripts/flamegraph.sh` per boundary revision")
    else:
        summary.append("no bad commit isolated in the sampled range")
    (outdir / "bisect.md").write_text("\n".join(summary) + "\n")
    print("\n".join(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
