#!/usr/bin/env python3
"""Interaction battery routed through the supervisor's accelerated chain.

Same pairwise methodology as basictex_interactions.py (reference vs
candidate page-count equivalence on cross-package style pairs), but the
candidate side compiles over the supervisor IPC so every request flows
through the production chain:

    X4 unchanged-rebuild gate -> X2 project format -> escalation.

Each reference-green case is compiled TWICE: once cold (X2 path builds
the project format) and once unchanged (X4 gate replays from cache) --
both PDFs must match the reference page count.

Requires a built release supervisor and the BasicTeX image.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "reference" / "basictex-2026"

sys.path.insert(0, str(ROOT / "scripts"))
from basictex_interactions import DOC_TEMPLATE, compile_once, pdf_page_count  # noqa: E402
from basictex_x2_edit_scenarios import Supervisor  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--ledger", type=Path,
                    default=REF / "package-ledger.json")
    ap.add_argument("--pairs", type=int, default=50)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--out", type=Path,
                    default=REF / "supervisor-interactions.json")
    args = ap.parse_args(argv)

    ledger = json.loads(args.ledger.read_text())
    representatives = []
    for row in ledger["rows"]:
        if row["loadable_styles"]:
            representatives.append(
                (row["package"], row["loadable_styles"][0]))
    universe = len(representatives)
    all_pairs = [(a, b)
                 for i, a in enumerate(representatives)
                 for b in representatives[i + 1:]]
    rng = random.Random(args.seed)
    rng.shuffle(all_pairs)
    shard_index, shard_total = (int(p) for p in args.shard.split("/"))
    selected = [pair for index, pair in enumerate(all_pairs)
                if index % shard_total == shard_index][:args.pairs]
    print(f"universe {universe} packages -> {len(all_pairs)} pairs; "
          f"testing {len(selected)}")

    root = Path(args.reference).resolve()
    binary_dir = root / "bin/universal-darwin"
    env = dict(os.environ)
    env["TEXMFROOT"] = str(root)
    env["PATH"] = f"{binary_dir}:{env.get('PATH', '')}"

    sup = Supervisor("int")
    counters = {"pass": 0, "cold-fail": 0, "warm-fail": 0,
                "reference-failure": 0}
    results = []
    try:
        for (package_a, style_a), (package_b, style_b) in selected:
            case_id = f"{package_a}+{package_b}"
            source = DOC_TEMPLATE % (style_a, style_b)

            reference_work = Path(tempfile.mkdtemp(prefix="bt100si-ref-"))
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
                shutil.rmtree(reference_work, ignore_errors=True)
                continue

            reference_pages = pdf_page_count(reference_work / "main.pdf")
            shutil.rmtree(reference_work, ignore_errors=True)

            # Candidate: fresh project dir, two supervisor compiles.
            work = Path(tempfile.mkdtemp(prefix="bt100si-cand-"))
            (work / "main.tex").write_text(source)
            payload = {
                "type": "compile",
                "profile": "basictex-2026",
                "cwd": str(work),
                "argv": ["pdflatex", "-interaction=batchmode",
                         "-jobname=main", "main.tex"],
                "snapshot_key": None,
            }

            def candidate_pages():
                response = sup.request(payload)
                accepted = response.get("compile_accepted", {})
                return (accepted.get("exit_status"),
                        pdf_page_count(work / "main.pdf"))

            cold_exit, cold_pages = candidate_pages()
            warm_exit, warm_pages = candidate_pages()  # X4 cache replay

            entry = {"case": case_id, "reference_pages": reference_pages,
                     "cold_pages": cold_pages, "warm_pages": warm_pages}
            if cold_exit != 0 or cold_pages != reference_pages:
                counters["cold-fail"] += 1
                entry["verdict"] = "fail"
                entry["stage"] = "cold"
                entry["candidate_exit"] = cold_exit
            elif warm_exit != 0 or warm_pages != reference_pages:
                counters["warm-fail"] += 1
                entry["verdict"] = "fail"
                entry["stage"] = "warm"
                entry["candidate_exit"] = warm_exit
            else:
                counters["pass"] += 1
                entry["verdict"] = "pass"
            results.append(entry)
            shutil.rmtree(work, ignore_errors=True)
    finally:
        sup.stop()

    out = {
        "schema_version": 1,
        "seed": args.seed,
        "shard": args.shard,
        "counters": counters,
        "results": results,
    }
    args.out.write_text(json.dumps(out, indent=2) + "\n")
    args.out.with_suffix(".md").write_text(
        "# Supervisor-path interactions\n\n| verdict | cases |\n|---|---:|\n"
        + "\n".join(f"| {k} | {v} |" for k, v in counters.items()) + "\n")
    print(counters, "->", args.out)
    return 0 if counters["cold-fail"] == 0 and counters["warm-fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
