#!/usr/bin/env python3
"""Classify BT100 interaction reference-failures.

For every reference-failure pair A+B from bt100-interactions.json,
determine whether the failure is *explained* by one of its components
already failing standalone in the smoke suite (smoke_verdict ==
'reference-failure'), or whether it is *pair-specific* (both components
compile alone under the reference but fail together).

Outputs reference/basictex-2026/ref-fail-classification.json (+ .md).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "reference" / "basictex-2026"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interactions", type=Path,
                    default=REF / "bt100-interactions.json")
    ap.add_argument("--ledger", type=Path, default=REF / "package-ledger.json")
    ap.add_argument("--out", type=Path, default=REF / "ref-fail-classification.json")
    args = ap.parse_args(argv)

    interactions = json.loads(args.interactions.read_text())
    ledger = json.loads(args.ledger.read_text())
    standalone_path = args.out.parent / "reffail-standalone.json"
    if not standalone_path.exists():
        sys.exit(f"missing {standalone_path}; run "
                 "basictex_reffail_standalone.py first")
    standalone = {r["package"]: r
                  for r in json.loads(
                      standalone_path.read_text())["results"]}

    results = interactions.get("results", [])
    ref_fails = [r for r in results if r["verdict"] == "reference-failure"]

    classified = Counter()
    pair_specific = []
    rows = []
    for r in ref_fails:
        parts = r["case"].split("+")
        culprits = sorted(
            p for p in parts
            if standalone.get(p, {}).get("verdict") == "standalone-fail"
            or standalone.get(p, {}).get("usepackage_verdict")
            == "standalone-fail")
        if culprits:
            cls = "explained-by-standalone-failure"
        else:
            cls = "pair-specific"
            pair_specific.append(r["case"])
        classified[cls] += 1
        rows.append({"case": r["case"], "class": cls, "culprits": culprits,
                     "culprit_errors": {c: standalone[c].get("error", "")
                                        for c in culprits}})

    # Which packages appear in pair-specific failures?
    ps_pkgs = Counter()
    for case in pair_specific:
        ps_pkgs.update(case.split("+"))

    out = {
        "schema_version": 1,
        "interactions_image_sha256": interactions.get("image_files_sha256"),
        "interactions_seed": interactions.get("seed"),
        "total_pairs": len(results),
        "ref_failures_total": len(ref_fails),
        "classified": dict(classified),
        "standalone_failed_packages": sorted(
            p for p, v in standalone.items()
            if v.get("verdict") == "standalone-fail"),
        "pair_specific_cases": pair_specific,
        "pair_specific_package_frequency": dict(
            ps_pkgs.most_common()),
        "rows": rows,
    }
    args.out.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")

    md = [
        "# Reference-failure classification",
        "",
        f"- total pairs: {len(results)}",
        f"- reference-failures: {len(ref_fails)}",
    ]
    for k, v in sorted(classified.items()):
        md.append(f"- `{k}`: {v}")
    top_ps = ", ".join(f"{p} ({n})" for p, n in ps_pkgs.most_common(12))
    md += ["", f"Top packages in pair-specific failures: {top_ps}", ""]
    args.out.with_suffix(".md").write_text("\n".join(md))

    print(f"classified: {dict(classified)}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
