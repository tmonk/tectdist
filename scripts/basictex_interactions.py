#!/usr/bin/env python3
"""BT100 package-interaction runner (plan §8.4).

Generates pairwise combinations of loadable styles drawn from different
packages, compiles each under BOTH the pinned BasicTeX reference and the
tectdist profile, and applies the same layered verdict as the single-package
smoke runner. Pair selection is deterministic given --seed so shards
reproduce exactly.

Usage:
    python3 scripts/basictex_interactions.py --reference <TL root> \
        --candidate /path/to/tectdist [--pairs 300] [--seed 11] [--shard i/n]
"""
import argparse
import json
import os
from pathlib import Path
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = ROOT / "reference/basictex-2026"

DOC_TEMPLATE = r"""\documentclass{article}
\usepackage{%s}
\usepackage{%s}
\begin{document}
Interaction smoke test.
\end{document}
"""


def pdf_page_count(pdf):
    tool = shutil.which("pdfinfo")
    if not tool:
        return None
    result = subprocess.run([tool, str(pdf)], capture_output=True, text=True)
    match = re.search(r"^Pages:\s*(\d+)\s*$", result.stdout, re.M)
    return int(match.group(1)) if match else None


def compile_once(binary_dir, work, source_name, env, timeout=90):
    try:
        return subprocess.run(
            [str(binary_dir / "pdflatex"), "-interaction=batchmode",
             "-halt-on-error", source_name],
            cwd=work, env=env, capture_output=True, text=True,
            timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--candidate", default=str(ROOT / "target/release/tectdist"))
    parser.add_argument("--ledger", default=str(REFERENCE_DIR / "package-ledger.json"))
    parser.add_argument("--output", default=str(REFERENCE_DIR / "bt100-interactions.json"))
    parser.add_argument("--markdown", default=str(REFERENCE_DIR / "bt100-interactions.md"))
    parser.add_argument("--pairs", type=int, default=300)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--shard", default="0/1")
    ns = parser.parse_args(argv)

    ledger = json.loads(Path(ns.ledger).read_text())
    # One representative style per package keeps pairs cross-package by
    # construction (same-package pairs are covered by the single-package run
    # when several styles exist).
    representatives = []
    for row in ledger["rows"]:
        if row["loadable_styles"]:
            representatives.append((row["package"], row["loadable_styles"][0]))

    rng = random.Random(ns.seed)
    universe = len(representatives)
    all_pairs = [(a, b)
                 for i, a in enumerate(representatives)
                 for b in representatives[i + 1:]]
    rng.shuffle(all_pairs)
    shard_index, shard_total = (int(part) for part in ns.shard.split("/"))
    selected = [pair for index, pair in enumerate(all_pairs)
                if index % shard_total == shard_index][:ns.pairs]

    root = Path(ns.reference).resolve()
    binary_dir = root / "bin/universal-darwin"
    env = dict(os.environ)
    env["TEXMFROOT"] = str(root)
    env["PATH"] = f"{binary_dir}:{env.get('PATH', '')}"
    link_dir = Path(tempfile.mkdtemp(prefix="bt100-inter-links-"))
    os.symlink(Path(ns.candidate).resolve(), link_dir / "pdflatex")
    profile_env = dict(env)
    profile_env["TECTDIST_PROFILE"] = "basictex-2026"
    profile_env["TECTDIST_BASICTEX_ROOT"] = str(root)
    profile_env["PATH"] = f"{link_dir}:{env['PATH']}"

    counters = {"pass": 0, "fail": 0, "reference-failure": 0}
    results = []
    for (package_a, style_a), (package_b, style_b) in selected:
        source = DOC_TEMPLATE % (style_a, style_b)
        case_id = f"{package_a}+{package_b}"

        reference_work = Path(tempfile.mkdtemp(prefix="bt100-int-ref-"))
        (reference_work / "main.tex").write_text(source)
        try:
            reference_status = compile_once(binary_dir, reference_work,
                                            "main.tex", env)
        except subprocess.TimeoutExpired:
            reference_status = None

        if reference_status != 0:
            counters["reference-failure"] += 1
            results.append({"case": case_id,
                            "verdict": "reference-failure"})
            continue

        candidate_work = Path(tempfile.mkdtemp(prefix="bt100-int-cand-"))
        (candidate_work / "main.tex").write_text(source)
        candidate_status = compile_once(link_dir, candidate_work,
                                        "main.tex", profile_env)
        reference_pages = pdf_page_count(reference_work / "main.pdf")
        candidate_pages = pdf_page_count(candidate_work / "main.pdf") \
            if candidate_status == 0 else None

        if candidate_status != 0 or candidate_pages != reference_pages:
            counters["fail"] += 1
            results.append({"case": case_id,
                            "verdict": "fail",
                            "candidate_exit": candidate_status,
                            "reference_pages": reference_pages,
                            "candidate_pages": candidate_pages})
        else:
            counters["pass"] += 1
            results.append({"case": case_id, "verdict": "pass"})

    report = {
        "schema_version": 1,
        "image_files_sha256": json.load(
            open(REFERENCE_DIR / "platform-manifest.json"))["image_files_sha256"],
        "shard": ns.shard,
        "seed": ns.seed,
        "universe_pairs": len(all_pairs),
        "counters": counters,
        "results": results,
    }
    Path(ns.output).write_text(json.dumps(report, indent=2) + "\n")

    lines = ["# BT100 interaction report", "",
             f"Shard {ns.shard}; seed {ns.seed}; "
             f"{ns.pairs} of {len(all_pairs)} possible pairs sampled",
             "", "| verdict | cases |", "|---|---:|"]
    for key, value in counters.items():
        lines.append(f"| {key} | {value} |")
    failures = [entry for entry in results if entry["verdict"] == "fail"]
    if failures:
        lines.extend(["", "## Failures", "", "| case | detail |", "|---|---|"])
        for entry in failures[:50]:
            lines.append("| %s | exit=%s pages ref=%s cand=%s |" % (
                entry["case"], entry.get("candidate_exit"),
                entry.get("reference_pages"), entry.get("candidate_pages")))
    Path(ns.markdown).write_text("\n".join(lines) + "\n")

    print(f"interactions: {counters['pass']} pass, {counters['fail']} fail, "
          f"{counters['reference-failure']} reference-failures "
          f"(sampled {sum(counters.values())}/{len(all_pairs)} pairs)")
    return 1 if counters["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
