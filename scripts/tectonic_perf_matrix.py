#!/usr/bin/env python3
"""Tectonic revision performance matrix (plan X3.1/X3.5).

Builds tectdist against each listed Tectonic revision, runs the benchmark
subset with correctness gates, and classifies every revision as good / bad /
unbuildable relative to the pinned baseline. Emits a raw JSON report plus a
Markdown summary so the release pin decision rests on measured evidence.

Usage:
    python3 scripts/tectonic_perf_matrix.py [--revisions FILE] [--output DIR]

The revisions file lists one `tag=<tectonic tag>` or `rev=<commit>` entry per
line (default: scripts/tectonic-matrix.toml). The workspace Cargo.toml and
Cargo.lock are backed up and restored around each build; a clean tree is
required.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ENGINE_TOML = ROOT / "crates/tectdist-engine/Cargo.toml"
WORKSPACE_TOML = ROOT / "Cargo.toml"
WORKSPACE_LOCK = ROOT / "Cargo.lock"

# Benchmark subset per plan X3.3: tiny, paper, QFT, and one font-heavy case.
MATRIX_DOCUMENTS = ["tiny", "paper", "unicode-fonts"]
OPTIONAL_DOCUMENTS = ["itp3-qft"]


def log(message):
    print(f"matrix: {message}", flush=True)


def sh(command, cwd=None, check=True):
    result = subprocess.run(command, cwd=cwd or ROOT, text=True,
                            capture_output=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed:\n{result.stdout}\n{result.stderr}")
    return result


def read_revisions(path):
    revisions = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        kind, _, value = line.partition("=")
        revisions.append((kind.strip(), value.strip()))
    return revisions


def rewrite_engine_dependency(kind, value):
    """Point the engine dependency at one revision; return old lines."""
    original = ENGINE_TOML.read_text()
    lines = []
    for line in original.splitlines(keepends=True):
        if "tectonic-typesetting/tectonic.git" in line:
            if kind == "rev":
                line = f'tectonic = {{ git = "https://github.com/tectonic-typesetting/tectonic.git", rev = "{value}", default-features = false, features = ["geturl-reqwest"], optional = true }}\n'
            else:
                line = line.replace("tag = \"tectonic@0.17.0\"", f"tag = \"{value}\"")
        lines.append(line)
    ENGINE_TOML.write_text("".join(lines))
    return original


def binary_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evaluate_revision(binary):
    """Run the untraced benchmark subset with correctness gates."""
    output = Path(os.environ.get("MATRIX_OUTPUT", "/tmp")) / \
        f"matrix-{os.getpid()}.json"
    environment = dict(os.environ)
    environment.setdefault("TECTDIST_BENCH_DIRECT_TECTONIC", "tectonic")
    command = [
        sys.executable, "-m", "benchmarks.runner.cli",
        "--candidate", str(binary),
        "--scenario", "warm-clean",
        "--trials", os.environ.get("MATRIX_TRIALS", "5"),
        "--warmups", "2",
        "--output", str(output),
    ]
    for document in MATRIX_DOCUMENTS:
        command.extend(["--document", document])
    for optional in OPTIONAL_DOCUMENTS:
        manifest = ROOT / f"benchmarks/external-manifests/{optional}.toml"
        if manifest.is_file():
            # Optional heavy fixtures run through their own manifest.
            continue
    result = subprocess.run(command, cwd=ROOT, env=environment,
                            capture_output=True, text=True)
    if result.returncode != 0:
        return None, result.stdout[-2000:] + result.stderr[-2000:]
    payload = json.loads(output.read_text())
    medians = {}
    for run in payload.get("runs", []):
        values = [sample["tools"]["candidate"]["wall_time_ms"]
                  for sample in run["samples"]]
        if values:
            values.sort()
            medians[run["document"]] = round(values[len(values) // 2], 1)
    output.unlink(missing_ok=True)
    return medians, None


def classify(medians, gate_ms):
    if medians is None:
        return "unmeasurable"
    tiny = medians.get("tiny")
    if tiny is None:
        return "unmeasurable"
    return "good" if tiny <= gate_ms else "bad"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revisions", default=str(ROOT / "scripts/tectonic-matrix.toml"))
    parser.add_argument("--gate-tiny-ms", type=float, default=150.0,
                        help="tiny median above this classifies a revision bad")
    parser.add_argument("--output", default=str(ROOT / "benchmark-results/matrix"))
    ns = parser.parse_args(argv)

    revisions = read_revisions(ns.revisions)
    outdir = Path(ns.output)
    outdir.mkdir(parents=True, exist_ok=True)

    workspace_original = WORKSPACE_TOML.read_text()
    lock_original = WORKSPACE_LOCK.read_text()

    report = {"schema_version": 1, "gate_tiny_ms": ns.gate_tiny_ms,
              "documents": MATRIX_DOCUMENTS, "revisions": []}
    try:
        for kind, value in revisions:
            label = f"{kind}:{value}"
            log(f"building {label}")
            entry = {"revision": label, "classification": "unbuildable"}
            try:
                original_engine_toml = rewrite_engine_dependency(kind, value)
                try:
                    sh(["cargo", "build", "--release", "-p", "tectdist-cli"])
                    binary = ROOT / "target/release/tectdist"
                    entry["binary_sha256"] = binary_sha256(binary)
                    medians, error = evaluate_revision(binary)
                    if medians is None:
                        entry["error"] = (error or "")[:500]
                    else:
                        entry["medians_ms"] = medians
                        entry["classification"] = classify(medians, ns.gate_tiny_ms)
                finally:
                    ENGINE_TOML.write_text(original_engine_toml)
                    shutil.copy2(WORKSPACE_LOCK, WORKSPACE_LOCK.with_suffix(".lock.bak"))
                    lock_backup = WORKSPACE_LOCK.with_suffix(".lock.bak")
                    if lock_backup.exists():
                        lock_backup.replace(WORKSPACE_LOCK)
                    # Restore lock from our own snapshot instead when present.
                    if not (ROOT / "Cargo.lock").exists():
                        WORKSPACE_LOCK.write_text(lock_original)
            except RuntimeError as error:
                entry["error"] = str(error)[:500]
            log(f"{label}: {entry['classification']}")
            report["revisions"].append(entry)
            (outdir / "matrix.json").write_text(json.dumps(report, indent=2) + "\n")
    finally:
        WORKSPACE_TOML.write_text(workspace_original)
        WORKSPACE_LOCK.write_text(lock_original)
        # Force Cargo to re-resolve against the restored inputs.
        sh(["cargo", "fetch"], check=False)

    lines = ["# Tectonic revision matrix", "",
             "| revision | tiny ms | paper ms | unicode-fonts ms | classification |",
             "|---|---:|---:|---:|---|"]
    for entry in report["revisions"]:
        medians = entry.get("medians_ms", {})
        lines.append("| %s | %s | %s | %s | %s |" % (
            entry["revision"], medians.get("tiny", "n/a"),
            medians.get("paper", "n/a"), medians.get("unicode-fonts", "n/a"),
            entry["classification"]))
    (outdir / "matrix.md").write_text("\n".join(lines) + "\n")
    log(f"report written to {outdir}/matrix.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
